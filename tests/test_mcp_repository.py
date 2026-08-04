"""Unit tests for the constrained Managed MCP repository mapping."""

from __future__ import annotations

from collections.abc import Mapping
from email.message import Message
from typing import Any

import pytest

from incident_memory.adapters.mcp import (
    ManagedMcpIncidentRepository,
    ManagedMcpToolClient,
    _decode_mcp_response,
    _extract_rows,
    _mcp_result_value,
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
    assert arguments["table"] == "incident_memories"
    assert arguments["rows"][0]["id"] == str(stored_incident.incident_id)
    assert arguments["rows"][0]["embedding"].startswith("[0.25,")


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

    def fake_call(name, arguments):
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

    def fail_call(name, arguments):
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
    def get_api_key(self) -> str:
        return "not-a-real-secret"


class FakeHttpResponse:
    def __init__(self, body: bytes, *, content_type: str, session_id: str | None = None) -> None:
        self._body = body
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if session_id:
            self.headers["Mcp-Session-Id"] = session_id

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, maximum: int) -> bytes:
        return self._body[:maximum]


class FakeOpener:
    def __init__(self) -> None:
        self.requests = []
        self.responses = [
            FakeHttpResponse(
                b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18"}}',
                content_type="application/json",
                session_id="test-session",
            ),
            FakeHttpResponse(b"", content_type="application/json"),
            FakeHttpResponse(
                (
                    b'data: {"jsonrpc":"2.0","id":2,"result":{"content":[],'
                    b'"structuredContent":{"rows":[]}}}\n\n'
                ),
                content_type="text/event-stream",
            ),
        ]

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return self.responses.pop(0)


def test_tool_client_performs_mcp_handshake_and_decodes_sse() -> None:
    client = ManagedMcpToolClient(
        url="https://cockroachlabs.cloud/mcp",
        cluster_id="11111111-1111-4111-8111-111111111111",
        api_key_provider=FakeApiKeyProvider(),
    )
    opener = FakeOpener()
    client._opener = opener

    result = client.call_tool("select_query", {"query": "fixed"})

    assert result == {"rows": []}
    assert len(opener.requests) == 3
    assert opener.requests[1][0].get_header("Mcp-session-id") == "test-session"
    assert opener.requests[2][0].get_header("Mcp-protocol-version") == "2025-06-18"


def test_decode_mcp_response_rejects_invalid_payload() -> None:
    with pytest.raises(AdapterContractError, match="invalid protocol"):
        _decode_mcp_response(b"not-json", "application/json")


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
