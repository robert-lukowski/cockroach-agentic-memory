"""Constrained CockroachDB Managed MCP repository adapter."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import UUID

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

from incident_memory.errors import AdapterContractError, ExternalServiceError
from incident_memory.models import IncidentEvidence, StoredIncident

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logging.getLogger("mcp").setLevel(logging.CRITICAL)
logging.getLogger("httpx2").setLevel(logging.CRITICAL)

_TABLE_NAME = "incident_memories"


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

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        if name not in {"insert_rows", "select_query"}:
            raise AdapterContractError("The MCP adapter rejected a non-allowlisted tool.")
        try:
            return asyncio.run(self._call_tool(name, dict(arguments)))
        except (AdapterContractError, ExternalServiceError):
            raise
        except Exception as error:
            raise ExternalServiceError("CockroachDB Managed MCP") from error

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        api_key = self._api_key_provider.get_api_key()
        logger.info("mcp_credential_loaded")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "mcp-cluster-id": self._cluster_id,
        }
        try:
            async with httpx2.AsyncClient(
                headers=headers,
                timeout=self._timeout_seconds,
                follow_redirects=False,
                trust_env=False,
                event_hooks={"response": [self._observe_response]},
            ) as http_client:
                async with streamable_http_client(
                    self._url,
                    http_client=http_client,
                ) as (read_stream, write_stream):
                    async with ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=self._timeout_seconds,
                    ) as session:
                        await session.initialize()
                        logger.info("mcp_session_initialized")
                        tools_result = await session.list_tools()
                        logger.info("mcp_tools_listed")
                        _tool_contract(_sdk_mapping(tools_result), name)
                        tool_result = await session.call_tool(name, arguments)
        except MCPError as error:
            _log_mcp_error(error)
            raise ExternalServiceError("CockroachDB Managed MCP") from error

        result = _sdk_mapping(tool_result)
        if result.get("isError") is True:
            category, sqlstate = _mcp_tool_error_category(result)
            logger.warning("mcp_tool_error_%s_sqlstate_%s", category, sqlstate or "none")
            raise ExternalServiceError("CockroachDB Managed MCP")
        logger.info("mcp_tool_completed", extra={"tool_name": name})
        return _mcp_result_value(result)

    async def _observe_response(self, response: httpx2.Response) -> None:
        if response.status_code not in {401, 403}:
            return
        logger.warning("mcp_http_error_%s", response.status_code)
        invalidate = getattr(self._api_key_provider, "invalidate", None)
        if callable(invalidate):
            invalidate()


def _sdk_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        mapped = model_dump(by_alias=True, exclude_none=True)
        if isinstance(mapped, Mapping):
            return mapped
    raise AdapterContractError("Managed MCP returned an invalid SDK result.")


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
        (
            "authentication",
            (
                "unauthorized",
                "authentication",
                "invalid token",
                "token expired",
                "api key",
            ),
        ),
        (
            "authorization",
            ("permission", "forbidden", "not authorized", "access denied", "role"),
        ),
        ("invalid_arguments", ("invalid argument", "validation", "required field")),
        ("statement_rejected", ("only insert", "only select", "not allowed", "must be an insert")),
        ("not_found", ("does not exist", "not found", "unknown database", "unknown table")),
        ("sql_syntax", ("syntax error", "parse error")),
        ("cluster_routing", ("cluster_id", "cluster id", "cluster access")),
        (
            "connectivity",
            ("failed to connect", "connection refused", "connection reset", "dial tcp"),
        ),
        (
            "tool_execution",
            ("failed to execute", "execution failed", "failed to run", "tool call failed"),
        ),
        ("service_unavailable", ("unavailable", "no healthy", "timeout", "timed out")),
        ("internal", ("internal error", "internal server")),
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


def _mcp_error_category(error: MCPError) -> tuple[str, str | None]:
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": error.message}],
    }
    if isinstance(error.data, Mapping):
        result["structuredContent"] = error.data
    return _mcp_tool_error_category(result)


def _log_mcp_error(error: MCPError) -> None:
    category, sqlstate = _mcp_error_category(error)
    logger.warning(
        "mcp_rpc_error_%s_category_%s_sqlstate_%s",
        error.code,
        category,
        sqlstate or "none",
    )


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
            "1 - distance AS similarity FROM ("
            "SELECT id, scope, service, environment, title, symptoms, root_cause, resolution, "
            f"tags, metadata, created_at, embedding <=> '{vector}'::VECTOR AS distance "
            f"FROM {_TABLE_NAME} WHERE {' AND '.join(predicates)} "
            f"ORDER BY distance LIMIT {int(limit)}) AS nearest ORDER BY distance"
        )
        result = self._tool_caller.call_tool(
            "select_query",
            {"database": self._database, "query": query},
        )
        rows = _extract_rows(result)
        return tuple(_evidence_from_row(row) for row in rows)


def _vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(format(float(value), ".7g") for value in values) + "]"


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
