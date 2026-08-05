"""Constrained CockroachDB Managed MCP repository adapter."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from incident_memory.errors import AdapterContractError, ExternalServiceError
from incident_memory.models import IncidentEvidence, StoredIncident

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_TABLE_NAME = "incident_memories"
_MCP_PROTOCOL_VERSION = "2025-06-18"
_MAX_RESPONSE_BYTES = 1_000_000


class McpToolCaller(Protocol):
    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """Call one allowlisted MCP tool."""


class ManagedMcpToolClient:
    """Authenticated Streamable HTTP client for the CockroachDB Managed MCP endpoint."""

    def __init__(
        self,
        *,
        url: str,
        cluster_id: str,
        api_key_provider: Any,
        timeout_seconds: float = 20.0,
    ) -> None:
        parsed_url = urlparse(url)
        if (
            parsed_url.scheme != "https"
            or parsed_url.hostname != "cockroachlabs.cloud"
            or parsed_url.path.rstrip("/") != "/mcp"
            or parsed_url.username
            or parsed_url.password
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise AdapterContractError("The Managed MCP endpoint is not approved.")
        self._url = url
        self._cluster_id = cluster_id
        self._api_key_provider = api_key_provider
        self._timeout_seconds = timeout_seconds
        self._opener = build_opener(_NoRedirectHandler())

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        if name not in {"insert_rows", "select_query"}:
            raise AdapterContractError("The MCP adapter rejected a non-allowlisted tool.")
        try:
            return self._call_tool(name, dict(arguments))
        except AdapterContractError:
            raise
        except Exception as error:
            raise ExternalServiceError("CockroachDB Managed MCP") from error

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        api_key = self._api_key_provider.get_api_key()
        logger.info("mcp_credential_loaded")
        initialized, session_id = self._post_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": _MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "agentic-incident-memory",
                        "version": "0.1.0",
                    },
                },
            },
            api_key=api_key,
            session_id=None,
        )
        logger.info("mcp_session_initialized")
        negotiated_version = str(
            _json_rpc_result(initialized).get("protocolVersion", _MCP_PROTOCOL_VERSION)
        )
        self._post_json_rpc(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            api_key=api_key,
            session_id=session_id,
            protocol_version=negotiated_version,
            allow_empty=True,
        )
        logger.info("mcp_client_initialized")
        tools_response, _ = self._post_json_rpc(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            api_key=api_key,
            session_id=session_id,
            protocol_version=negotiated_version,
        )
        properties, required = _tool_contract(_json_rpc_result(tools_response), name)
        logger.info(
            "mcp_tool_contract_%s_properties_%s_required_%s",
            name,
            ",".join(properties),
            ",".join(required),
        )
        response, _ = self._post_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": {**arguments, "cluster_id": self._cluster_id},
                },
            },
            api_key=api_key,
            session_id=session_id,
            protocol_version=negotiated_version,
        )
        result = _json_rpc_result(response)
        if result.get("isError") is True:
            category, sqlstate = _mcp_tool_error_category(result)
            logger.warning("mcp_tool_error_%s_sqlstate_%s", category, sqlstate or "none")
            raise ExternalServiceError("CockroachDB Managed MCP")
        logger.info("mcp_tool_completed", extra={"tool_name": name})
        return _mcp_result_value(result)

    def _post_json_rpc(
        self,
        payload: Mapping[str, Any],
        *,
        api_key: str,
        session_id: str | None,
        protocol_version: str | None = None,
        allow_empty: bool = False,
    ) -> tuple[Mapping[str, Any] | None, str | None]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "mcp-cluster-id": self._cluster_id,
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        if protocol_version:
            headers["MCP-Protocol-Version"] = protocol_version
        request = Request(
            self._url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                body = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise AdapterContractError("Managed MCP returned an oversized response.")
                returned_session_id = response.headers.get("Mcp-Session-Id") or session_id
                content_type = response.headers.get("Content-Type", "")
        except HTTPError as error:
            logger.warning("mcp_http_error_%s", error.code)
            if error.code in {401, 403}:
                invalidate = getattr(self._api_key_provider, "invalidate", None)
                if callable(invalidate):
                    invalidate()
            raise ExternalServiceError("CockroachDB Managed MCP") from error
        except URLError as error:
            logger.warning("mcp_network_error")
            raise ExternalServiceError("CockroachDB Managed MCP") from error
        if not body:
            if allow_empty:
                return None, returned_session_id
            raise AdapterContractError("Managed MCP returned an empty response.")
        return _decode_mcp_response(body, content_type), returned_session_id


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        del request, fp, code, message, headers, new_url
        return None


def _decode_mcp_response(body: bytes, content_type: str) -> Mapping[str, Any]:
    try:
        text = body.decode("utf-8")
        if "text/event-stream" in content_type.lower():
            data_lines = [
                line[5:].lstrip() for line in text.splitlines() if line.startswith("data:")
            ]
            text = "\n".join(data_lines)
        value = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdapterContractError("Managed MCP returned an invalid protocol response.") from error
    if not isinstance(value, Mapping):
        raise AdapterContractError("Managed MCP returned an invalid protocol response.")
    return value


def _json_rpc_result(response: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if response is None:
        raise ExternalServiceError("CockroachDB Managed MCP")
    if "error" in response:
        error = response.get("error")
        error_mapping = error if isinstance(error, Mapping) else {}
        category, sqlstate = _mcp_tool_error_category(
            {"structuredContent": error_mapping}
        )
        raw_code = error_mapping.get("code")
        code = str(raw_code) if isinstance(raw_code, int) else "unknown"
        logger.warning(
            "mcp_rpc_error_%s_category_%s_sqlstate_%s",
            code,
            category,
            sqlstate or "none",
        )
        raise ExternalServiceError("CockroachDB Managed MCP")
    result = response.get("result")
    if not isinstance(result, Mapping):
        raise AdapterContractError("Managed MCP returned an invalid JSON-RPC result.")
    return result


def _mcp_result_value(result: Any) -> Any:
    structured = result.get("structuredContent") if isinstance(result, Mapping) else None
    if structured is not None:
        return structured
    texts = [
        item["text"]
        for item in result.get("content", [])
        if isinstance(item, Mapping) and item.get("type") == "text" and "text" in item
    ]
    combined = "\n".join(texts).strip()
    if not combined:
        return None
    try:
        return json.loads(combined)
    except json.JSONDecodeError:
        return combined


def _tool_contract(result: Mapping[str, Any], name: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    tools = result.get("tools")
    if not isinstance(tools, list):
        raise AdapterContractError("Managed MCP returned an invalid tool catalog.")
    for tool in tools:
        if not isinstance(tool, Mapping) or tool.get("name") != name:
            continue
        schema = tool.get("inputSchema")
        if not isinstance(schema, Mapping):
            raise AdapterContractError("Managed MCP returned an invalid tool schema.")
        raw_properties = schema.get("properties", {})
        raw_required = schema.get("required", [])
        if not isinstance(raw_properties, Mapping) or not isinstance(raw_required, list):
            raise AdapterContractError("Managed MCP returned an invalid tool schema.")
        properties = tuple(
            sorted(
                f"{key}:{value.get('type', 'unknown')}"
                for key, value in raw_properties.items()
                if isinstance(key, str) and isinstance(value, Mapping)
            )
        )
        required = tuple(sorted(item for item in raw_required if isinstance(item, str)))
        return properties, required
    raise AdapterContractError("The required Managed MCP tool is unavailable.")


def _mcp_tool_error_category(result: Mapping[str, Any]) -> tuple[str, str | None]:
    fragments = [
        item.get("text", "")
        for item in result.get("content", [])
        if isinstance(item, Mapping) and item.get("type") == "text"
    ]
    structured = result.get("structuredContent")
    if isinstance(structured, Mapping):
        fragments.append(json.dumps(structured, ensure_ascii=True, separators=(",", ":")))
    text = " ".join(fragment for fragment in fragments if isinstance(fragment, str))[:20_000]
    normalized = text.lower()
    categories = (
        ("authorization", ("permission", "forbidden", "not authorized", "access denied", "role")),
        ("invalid_arguments", ("invalid argument", "validation", "required field")),
        ("statement_rejected", ("only insert", "only select", "not allowed", "must be an insert")),
        ("not_found", ("does not exist", "not found", "unknown database", "unknown table")),
        ("sql_syntax", ("syntax error", "parse error")),
        ("database", ("sqlstate", "database error", "cockroach")),
    )
    category = next(
        (name for name, markers in categories if any(marker in normalized for marker in markers)),
        "unknown",
    )
    state_match = re.search(
        r"\bsqlstate\s*([0-9A-Z]{5})\b|\(([0-9A-Z]{5})\)",
        text,
        re.IGNORECASE,
    )
    state = next((group for group in state_match.groups() if group), None) if state_match else None
    return category, state.upper() if state else None


class ManagedMcpIncidentRepository:
    """Maps narrow repository operations to fixed Managed MCP tools."""

    def __init__(self, *, tool_caller: McpToolCaller, database: str) -> None:
        self._tool_caller = tool_caller
        self._database = database

    def save(self, incident: StoredIncident) -> None:
        tags = json.dumps(list(incident.tags), ensure_ascii=False, separators=(",", ":"))
        metadata = json.dumps(incident.metadata, ensure_ascii=False, separators=(",", ":"))
        vector = _vector_literal(incident.embedding)
        query = (
            f"INSERT INTO {_TABLE_NAME} "
            "(id, scope, service, environment, title, symptoms, root_cause, resolution, "
            "tags, metadata, embedding, created_at) VALUES ("
            f"{_sql_literal(str(incident.incident_id))}::UUID, "
            f"{_sql_literal(incident.scope)}, {_sql_literal(incident.service)}, "
            f"{_sql_literal(incident.environment)}, {_sql_literal(incident.title)}, "
            f"{_sql_literal(incident.symptoms)}, {_sql_literal(incident.root_cause)}, "
            f"{_sql_literal(incident.resolution)}, {_sql_literal(tags)}::JSONB, "
            f"{_sql_literal(metadata)}::JSONB, {_sql_literal(vector)}::VECTOR, "
            f"{_sql_literal(incident.created_at.isoformat())}::TIMESTAMPTZ)"
        )
        self._tool_caller.call_tool(
            "insert_rows",
            {"database": self._database, "query": query},
        )

    def find_similar(
        self,
        *,
        scope: str,
        embedding: Sequence[float],
        limit: int,
        service: str | None,
        environment: str | None,
    ) -> Sequence[IncidentEvidence]:
        vector = _vector_literal(embedding)
        predicates = [f"scope = {_sql_literal(scope)}"]
        if service is not None:
            predicates.append(f"service = {_sql_literal(service)}")
        if environment is not None:
            predicates.append(f"environment = {_sql_literal(environment)}")
        query = (
            "SELECT id::STRING AS incident_id, scope, service, environment, title, symptoms, "
            "root_cause, resolution, tags, metadata, created_at::STRING AS created_at, "
            f"1 - (embedding <=> '{vector}'::VECTOR) AS similarity "
            f"FROM {_TABLE_NAME} WHERE {' AND '.join(predicates)} "
            f"ORDER BY embedding <=> '{vector}'::VECTOR LIMIT {int(limit)}"
        )
        result = self._tool_caller.call_tool(
            "select_query",
            {"database": self._database, "query": query},
        )
        rows = _extract_rows(result)
        return tuple(_evidence_from_row(row) for row in rows)


def _vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(format(float(value), ".12g") for value in values) + "]"


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _extract_rows(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
        return value
    if isinstance(value, Mapping):
        for key in ("rows", "data", "result"):
            candidate = value.get(key)
            if isinstance(candidate, list) and all(isinstance(item, Mapping) for item in candidate):
                return candidate
            if isinstance(candidate, Mapping):
                try:
                    return _extract_rows(candidate)
                except AdapterContractError:
                    pass
    raise AdapterContractError("Managed MCP returned an unsupported query result shape.")


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise AdapterContractError("Managed MCP returned invalid JSON metadata.")


def _json_tags(value: Any) -> tuple[str, ...]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise AdapterContractError("Managed MCP returned invalid incident tags.")
    return tuple(parsed)


def _evidence_from_row(row: Mapping[str, Any]) -> IncidentEvidence:
    try:
        created_at = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        incident = StoredIncident(
            incident_id=UUID(str(row["incident_id"])),
            scope=str(row["scope"]),
            service=str(row["service"]),
            environment=str(row["environment"]),
            title=str(row["title"]),
            symptoms=str(row["symptoms"]),
            root_cause=str(row["root_cause"]),
            resolution=str(row["resolution"]),
            tags=_json_tags(row["tags"]),
            metadata=_json_object(row["metadata"]),
            embedding=(),
            created_at=created_at,
        )
        similarity = float(row["similarity"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise AdapterContractError("Managed MCP returned an invalid incident row.") from error
    return IncidentEvidence(incident=incident, similarity=similarity)
