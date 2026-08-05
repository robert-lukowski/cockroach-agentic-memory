"""Unit tests for the constrained Managed MCP repository mapping."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.shared.exceptions import MCPError

import incident_memory.adapters.mcp as mcp_adapter
from incident_memory.adapters.mcp import (
    ManagedMcpIncidentRepository,
    ManagedMcpToolClient,
    _extract_rows,
    _log_mcp_error,
    _mcp_result_value,
    _mcp_tool_error_category,
    _sdk_mapping,
    _tool_contract,
)
from incident_memory.errors import AdapterContractError, ExternalServiceError
from incident_memory.models import EMBEDDING_DIMENSIONS


class FakeToolCaller:
    def __init__(self, result: object = None) -> None:
        self.result = result
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        self.calls.append((name, arguments))
        return self.result


def test_save_maps_incident_to_insert_rows(stored_incident) -> None:
    caller = FakeToolCaller()
    repository = ManagedMcpIncidentRepository(tool_caller=caller, database="defaultdb")

    repository.save(stored_incident)

    name, arguments = caller.calls[0]
    assert name == "insert_rows"
    assert arguments["database"] == "defaultdb"
    assert arguments.keys() == {"database", "query"}
    assert "INSERT INTO incident_memories" in arguments["query"]
    assert str(stored_incident.incident_id) in arguments["query"]
    assert "'[0.25,0.25," in arguments["query"]
    assert "::VECTOR" in arguments["query"]
    assert "ON CONFLICT (id) DO UPDATE" in arguments["query"]


def test_find_by_id_uses_fixed_primary_key_query(stored_incident) -> None:
    caller = FakeToolCaller(
        {
            "rows": [
                {
                    "incident_id": str(stored_incident.incident_id),
                    "scope": stored_incident.scope,
                    "service": stored_incident.service,
                    "environment": stored_incident.environment,
                    "title": stored_incident.title,
                    "symptoms": stored_incident.symptoms,
                    "root_cause": stored_incident.root_cause,
                    "resolution": stored_incident.resolution,
                    "tags": list(stored_incident.tags),
                    "metadata": stored_incident.metadata,
                    "created_at": stored_incident.created_at.isoformat(),
                }
            ]
        }
    )
    repository = ManagedMcpIncidentRepository(tool_caller=caller, database="defaultdb")

    result = repository.find_by_id(stored_incident.incident_id)

    assert result == stored_incident.__class__(
        incident_id=stored_incident.incident_id,
        scope=stored_incident.scope,
        service=stored_incident.service,
        environment=stored_incident.environment,
        title=stored_incident.title,
        symptoms=stored_incident.symptoms,
        root_cause=stored_incident.root_cause,
        resolution=stored_incident.resolution,
        tags=stored_incident.tags,
        metadata=stored_incident.metadata,
        embedding=(),
        created_at=stored_incident.created_at,
    )
    name, arguments = caller.calls[0]
    assert name == "select_query"
    assert "WHERE id = '11111111-1111-4111-8111-111111111111'::UUID LIMIT 1" in arguments[
        "query"
    ]


def test_find_by_id_returns_none_for_no_rows(stored_incident) -> None:
    repository = ManagedMcpIncidentRepository(
        tool_caller=FakeToolCaller({"rows": []}),
        database="defaultdb",
    )

    assert repository.find_by_id(stored_incident.incident_id) is None


def test_find_similar_builds_fixed_query_and_maps_rows(stored_incident) -> None:
    caller = FakeToolCaller(
        {
            "rows": [
                {
                    "incident_id": str(stored_incident.incident_id),
                    "scope": stored_incident.scope,
                    "service": stored_incident.service,
                    "environment": stored_incident.environment,
                    "title": stored_incident.title,
                    "symptoms": stored_incident.symptoms,
                    "root_cause": stored_incident.root_cause,
                    "resolution": stored_incident.resolution,
                    "tags": '["database","latency"]',
                    "metadata": {"severity": "SEV-2"},
                    "created_at": stored_incident.created_at.isoformat(),
                    "similarity": "0.93",
                }
            ]
        }
    )
    repository = ManagedMcpIncidentRepository(tool_caller=caller, database="defaultdb")

    results = repository.find_similar(
        scope="hackathon-demo",
        embedding=(0.25,) * EMBEDDING_DIMENSIONS,
        limit=3,
        service="pay'ments",
        environment="production",
    )

    assert len(results) == 1
    assert results[0].incident.incident_id == stored_incident.incident_id
    assert results[0].similarity == 0.93
    name, arguments = caller.calls[0]
    assert name == "select_query"
    assert "scope = 'hackathon-demo'" in arguments["query"]
    assert "service = 'pay''ments'" in arguments["query"]
    assert "LIMIT 3" in arguments["query"]
    assert arguments["query"].count("'[0.25,0.25,") == 1


def test_extract_rows_supports_nested_result() -> None:
    assert _extract_rows({"result": {"data": [{"id": "one"}]}}) == [{"id": "one"}]


def test_extract_rows_rejects_unknown_shape() -> None:
    with pytest.raises(AdapterContractError, match="unsupported"):
        _extract_rows({"message": "no rows"})


def test_mcp_result_prefers_structured_content() -> None:
    result = {"content": [], "structuredContent": {"rows": []}}

    assert _mcp_result_value(result) == {"rows": []}


def test_mcp_result_decodes_json_text() -> None:
    result = {"content": [{"type": "text", "text": '{"rows":[]}'}]}

    assert _mcp_result_value(result) == {"rows": []}


def test_mcp_result_returns_plain_text_and_empty_content() -> None:
    plain = {"content": [{"type": "text", "text": "plain result"}]}
    empty = {"content": []}

    assert _mcp_result_value(plain) == "plain result"
    assert _mcp_result_value(empty) is None


def test_tool_client_rejects_unallowlisted_tool() -> None:
    client = ManagedMcpToolClient(
        url="https://cockroachlabs.cloud/mcp",
        cluster_id="11111111-1111-4111-8111-111111111111",
        api_key_provider=object(),
    )

    with pytest.raises(AdapterContractError, match="non-allowlisted"):
        client.call_tool("create_database", {})


def test_tool_client_runs_allowlisted_call(monkeypatch) -> None:
    client = ManagedMcpToolClient(
        url="https://cockroachlabs.cloud/mcp",
        cluster_id="11111111-1111-4111-8111-111111111111",
        api_key_provider=object(),
    )

    async def fake_call(name, arguments):
        return {"name": name, "arguments": arguments}

    monkeypatch.setattr(client, "_call_tool", fake_call)

    assert client.call_tool("select_query", {"query": "fixed"}) == {
        "name": "select_query",
        "arguments": {"query": "fixed"},
    }


def test_tool_client_redacts_transport_failure(monkeypatch) -> None:
    client = ManagedMcpToolClient(
        url="https://cockroachlabs.cloud/mcp",
        cluster_id="11111111-1111-4111-8111-111111111111",
        api_key_provider=object(),
    )

    async def fail_call(name, arguments):
        del name, arguments
        raise RuntimeError("sensitive-transport-detail")

    monkeypatch.setattr(client, "_call_tool", fail_call)

    with pytest.raises(ExternalServiceError) as captured:
        client.call_tool("select_query", {})

    assert "sensitive-transport-detail" not in str(captured.value)


def test_tool_client_rejects_non_managed_endpoint() -> None:
    with pytest.raises(AdapterContractError, match="not approved"):
        ManagedMcpToolClient(
            url="https://example.com/mcp",
            cluster_id="11111111-1111-4111-8111-111111111111",
            api_key_provider=object(),
        )


class FakeApiKeyProvider:
    def __init__(self) -> None:
        self.invalidations = 0

    def get_api_key(self) -> str:
        return "not-a-real-secret"

    def invalidate(self) -> None:
        self.invalidations += 1


class FakeSdkModel:
    def __init__(self, value: Mapping[str, Any]) -> None:
        self.value = value

    def model_dump(self, *, by_alias: bool, exclude_none: bool) -> Mapping[str, Any]:
        assert by_alias is True
        assert exclude_none is True
        return self.value


def test_tool_client_uses_one_sdk_session_for_initialize_list_and_call(
    monkeypatch, caplog
) -> None:
    events: list[tuple[str, int | None]] = []
    clients: list[Any] = []
    sessions: list[Any] = []

    class FakeHttpClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            clients.append(self)

        async def __aenter__(self):
            events.append(("http_enter", None))
            return self

        async def __aexit__(self, *args):
            events.append(("http_exit", None))
            return False

    @asynccontextmanager
    async def fake_streamable_http_client(url, *, http_client):
        assert url == "https://cockroachlabs.cloud/mcp"
        assert http_client is clients[0]
        events.append(("transport_enter", None))
        yield "read-stream", "write-stream"
        events.append(("transport_exit", None))

    class FakeClientSession:
        def __init__(self, read_stream, write_stream, *, read_timeout_seconds) -> None:
            assert (read_stream, write_stream) == ("read-stream", "write-stream")
            assert read_timeout_seconds == 20.0
            self.entered = False
            self.initialized = False
            self.tools_listed = False
            sessions.append(self)

        async def __aenter__(self):
            self.entered = True
            events.append(("session_enter", id(self)))
            return self

        async def __aexit__(self, *args):
            events.append(("session_exit", id(self)))
            self.entered = False
            return False

        async def initialize(self):
            assert self.entered
            self.initialized = True
            events.append(("initialize", id(self)))

        async def list_tools(self):
            assert self.entered and self.initialized
            self.tools_listed = True
            events.append(("list_tools", id(self)))
            return FakeSdkModel(
                {
                    "tools": [
                        {
                            "name": "select_query",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "database": {"type": "string"},
                                    "query": {"type": "string"},
                                    "sensitive_provider_property": {"type": "string"},
                                },
                                "required": ["database", "query"],
                            },
                        }
                    ]
                }
            )

        async def call_tool(self, name, arguments):
            assert self.entered and self.initialized and self.tools_listed
            events.append(("call_tool", id(self)))
            assert name == "select_query"
            assert arguments == {"database": "defaultdb", "query": "fixed"}
            return FakeSdkModel(
                {"content": [], "structuredContent": {"rows": []}, "isError": False}
            )

    monkeypatch.setattr(mcp_adapter.httpx2, "AsyncClient", FakeHttpClient)
    monkeypatch.setattr(mcp_adapter, "streamable_http_client", fake_streamable_http_client)
    monkeypatch.setattr(mcp_adapter, "ClientSession", FakeClientSession)
    client = ManagedMcpToolClient(
        url="https://cockroachlabs.cloud/mcp",
        cluster_id="11111111-1111-4111-8111-111111111111",
        api_key_provider=FakeApiKeyProvider(),
    )

    with caplog.at_level("INFO"):
        result = client.call_tool(
            "select_query", {"database": "defaultdb", "query": "fixed"}
        )

    assert result == {"rows": []}
    assert len(sessions) == 1
    session_id = id(sessions[0])
    assert [(name, owner) for name, owner in events if owner is not None] == [
        ("session_enter", session_id),
        ("initialize", session_id),
        ("list_tools", session_id),
        ("call_tool", session_id),
        ("session_exit", session_id),
    ]
    assert clients[0].kwargs["headers"] == {
        "Authorization": "Bearer not-a-real-secret",
        "mcp-cluster-id": "11111111-1111-4111-8111-111111111111",
    }
    assert "mcp_session_initialized" in caplog.text
    assert "mcp_tools_listed" in caplog.text
    assert "mcp_tool_completed" in caplog.text
    assert "sensitive_provider_property" not in caplog.text
    assert "not-a-real-secret" not in caplog.text


def test_tool_client_invalidates_cached_key_on_auth_http_response() -> None:
    provider = FakeApiKeyProvider()
    client = ManagedMcpToolClient(
        url="https://cockroachlabs.cloud/mcp",
        cluster_id="11111111-1111-4111-8111-111111111111",
        api_key_provider=provider,
    )

    asyncio.run(client._observe_response(SimpleNamespace(status_code=401)))
    asyncio.run(client._observe_response(SimpleNamespace(status_code=200)))

    assert provider.invalidations == 1


def test_sdk_mapping_uses_aliases_and_rejects_unknown_value() -> None:
    assert _sdk_mapping(FakeSdkModel({"structuredContent": {"rows": []}})) == {
        "structuredContent": {"rows": []}
    }
    with pytest.raises(AdapterContractError, match="invalid SDK result"):
        _sdk_mapping(object())


def test_tool_contract_returns_static_property_types_and_required_fields() -> None:
    properties, required = _tool_contract(
        {
            "tools": [
                {
                    "name": "insert_rows",
                    "inputSchema": {
                        "properties": {"rows": {"type": "array"}, "table": {"type": "string"}},
                        "required": ["table", "rows"],
                    },
                }
            ]
        },
        "insert_rows",
    )

    assert properties == ("rows:array", "table:string")
    assert required == ("rows", "table")


@pytest.mark.parametrize(
    ("catalog", "message"),
    [
        ({}, "invalid tool catalog"),
        ({"tools": [{"name": "another_tool"}]}, "unavailable"),
        ({"tools": [{"name": "insert_rows", "inputSchema": "invalid"}]}, "invalid tool schema"),
        (
            {
                "tools": [
                    {
                        "name": "insert_rows",
                        "inputSchema": {"properties": [], "required": "invalid"},
                    }
                ]
            },
            "invalid tool schema",
        ),
    ],
)
def test_tool_contract_rejects_invalid_catalogs(catalog, message) -> None:
    with pytest.raises(AdapterContractError, match=message):
        _tool_contract(catalog, "insert_rows")


@pytest.mark.parametrize(
    ("message", "expected_category", "expected_sqlstate"),
    [
        ("unauthorized service account API key", "authentication", None),
        ("permission denied for cluster", "authorization", None),
        ("invalid argument: database is required", "invalid_arguments", None),
        ("statement not allowed by tool", "statement_rejected", None),
        ("relation does not exist (SQLSTATE 42P01)", "not_found", "42P01"),
        ("syntax error at token (42601)", "sql_syntax", "42601"),
        ("cluster_id does not match configured scope", "cluster_routing", None),
        ("failed to connect to SQL endpoint", "connectivity", None),
        ("failed to execute tool request", "tool_execution", None),
        ("backend service unavailable", "service_unavailable", None),
        ("internal server failure", "internal", None),
        ("opaque provider failure", "unknown", None),
    ],
)
def test_mcp_tool_error_classification(message, expected_category, expected_sqlstate) -> None:
    result = {"content": [{"type": "text", "text": message}], "isError": True}

    assert _mcp_tool_error_category(result) == (expected_category, expected_sqlstate)


def test_sdk_json_rpc_error_logs_only_redacted_classification(caplog) -> None:
    error = MCPError(-32602, "invalid argument sensitive-provider-detail")
    with caplog.at_level("WARNING"):
        _log_mcp_error(error)

    assert "mcp_rpc_error_-32602_category_invalid_arguments_sqlstate_none" in caplog.text
    assert "sensitive-provider-detail" not in caplog.text


def test_repository_rejects_invalid_incident_row(stored_incident) -> None:
    caller = FakeToolCaller({"rows": [{"incident_id": str(stored_incident.incident_id)}]})
    repository = ManagedMcpIncidentRepository(tool_caller=caller, database="defaultdb")

    with pytest.raises(AdapterContractError, match="invalid incident row"):
        repository.find_similar(
            scope="hackathon-demo",
            embedding=(0.25,) * EMBEDDING_DIMENSIONS,
            limit=1,
            service=None,
            environment=None,
        )
