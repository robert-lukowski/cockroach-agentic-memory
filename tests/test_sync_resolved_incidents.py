"""Tests for resolved-only synchronization through the signed backend API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from botocore.credentials import Credentials

from scripts.sync_resolved_incidents import (
    ALLOWED_METADATA_FIELDS,
    BackendError,
    HttpResponse,
    SignedIncidentClient,
    SyncConfigurationError,
    build_memory_payload,
    synchronize_records,
)

DATASET = json.loads(Path("data/servicenow_demo_incidents.json").read_text(encoding="utf-8"))


class FakeMemoryClient:
    def __init__(self) -> None:
        self.memories: dict[str, dict[str, Any]] = {}
        self.calls: list[dict[str, Any]] = []

    def submit(self, payload):
        clean = dict(payload)
        clean.pop("verify_only", None)
        source_id = clean["source_id"]
        existing = self.memories.get(source_id)
        self.calls.append(dict(payload))
        if payload.get("verify_only"):
            if existing == clean:
                status = "already_present"
            else:
                status = "absent" if existing is None else "different"
            return 200, {"status": status, "incident_id": "synthetic"}
        if existing is None:
            status_code, status = 201, "created"
        elif existing == clean:
            status_code, status = 200, "already_present"
        else:
            status_code, status = 200, "updated"
        self.memories[source_id] = clean
        return status_code, {"status": status, "incident_id": "synthetic"}


class FakeTransport:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeSession:
    def __init__(self, credentials=True) -> None:
        self.credentials = (
            Credentials("synthetic-access", "synthetic-secret", "synthetic-session")
            if credentials
            else None
        )

    def get_credentials(self):
        return self.credentials


def test_memory_mapping_uses_only_approved_fields() -> None:
    record = DATASET[0]

    payload = build_memory_payload(record)

    assert payload["source_id"] == f"servicenow:demo:{record['incident_sys_id']}"
    assert payload["scope"] == "servicenow-dev"
    assert payload["service"] == record["cmdb_ci"]
    assert payload["environment"] == "development"
    assert payload["title"] == record["short_description"]
    assert payload["symptoms"] == record["description"]
    assert payload["root_cause"] == record["root_cause"]
    assert payload["resolution"] == record["resolution"]
    assert set(payload["metadata"]) == ALLOWED_METADATA_FIELDS
    assert {"servicenow", "synthetic-demo", "resolved-memory"} <= set(payload["tags"])
    assert "authorization" not in json.dumps(payload).lower()


def test_active_record_cannot_be_mapped_to_memory() -> None:
    with pytest.raises(SyncConfigurationError, match="resolved"):
        build_memory_payload(DATASET[2])


def test_only_resolved_records_are_sent() -> None:
    client = FakeMemoryClient()

    summary = synchronize_records(DATASET, client=client)

    assert summary.selected_resolved == 20
    assert summary.skipped_active == 10
    assert summary.created == 20
    assert len(client.calls) == 20
    assert all(call["root_cause"] and call["resolution"] for call in client.calls)
    active_sources = {record["source_id"] for record in DATASET if record["active"]}
    assert active_sources.isdisjoint(call["source_id"] for call in client.calls)


def test_repeated_sync_is_idempotent() -> None:
    client = FakeMemoryClient()

    first = synchronize_records(DATASET, client=client)
    second = synchronize_records(DATASET, client=client)

    assert first.created == 20
    assert second.created == 0
    assert second.updated == 0
    assert second.already_present == 20
    assert len(client.memories) == 20


def test_verify_only_does_not_create_absent_memories() -> None:
    client = FakeMemoryClient()

    summary = synchronize_records(
        DATASET,
        client=client,
        verify_only=True,
        limit=2,
        warning=lambda _: None,
    )

    assert summary.selected_resolved == 2
    assert summary.failed == 2
    assert client.memories == {}
    assert all(call["verify_only"] is True for call in client.calls)


def test_dry_run_needs_no_credentials_or_network() -> None:
    summary = synchronize_records(DATASET, client=None, dry_run=True, limit=3)

    assert summary.selected_resolved == 3
    assert summary.created == 0
    assert summary.failed == 0


def test_sigv4_signing_and_bounded_retry() -> None:
    transport = FakeTransport(
        [
            HttpResponse(429, b"provider detail"),
            HttpResponse(503, b"provider detail"),
            HttpResponse(201, b'{"status":"created","incident_id":"synthetic"}'),
        ]
    )
    sleeps: list[float] = []
    client = SignedIncidentClient(
        api_base_url="https://example.execute-api.eu-central-1.amazonaws.com/v1",
        session=FakeSession(),
        transport=transport,
        sleep=sleeps.append,
    )

    status, body = client.submit(build_memory_payload(DATASET[0]))

    assert status == 201
    assert body["status"] == "created"
    assert len(transport.calls) == 3
    assert sleeps == [1.0, 2.0]
    assert all(call["timeout"] == 45.0 for call in transport.calls)
    assert all(
        call["headers"]["Authorization"].startswith("AWS4-HMAC-SHA256")
        for call in transport.calls
    )
    assert all(
        call["headers"]["X-Amz-Security-Token"] == "synthetic-session"
        for call in transport.calls
    )


@pytest.mark.parametrize("status", [400, 401, 403])
def test_nonretryable_backend_statuses_are_safe(status: int) -> None:
    transport = FakeTransport([HttpResponse(status, b"synthetic-secret provider detail")])
    client = SignedIncidentClient(
        api_base_url="https://example.execute-api.eu-central-1.amazonaws.com/v1",
        session=FakeSession(),
        transport=transport,
    )

    with pytest.raises(BackendError) as captured:
        client.submit(build_memory_payload(DATASET[0]))

    assert len(transport.calls) == 1
    assert "synthetic-secret" not in str(captured.value)
    assert "provider detail" not in str(captured.value)


def test_transient_5xx_stops_after_bounded_attempts() -> None:
    transport = FakeTransport([HttpResponse(500, b"")] * 3)
    client = SignedIncidentClient(
        api_base_url="https://example.execute-api.eu-central-1.amazonaws.com/v1",
        session=FakeSession(),
        transport=transport,
        sleep=lambda _: None,
    )

    with pytest.raises(BackendError) as captured:
        client.submit(build_memory_payload(DATASET[0]))

    assert captured.value.status == 500
    assert len(transport.calls) == 3


def test_missing_aws_credentials_fails_closed() -> None:
    with pytest.raises(SyncConfigurationError, match="credentials"):
        SignedIncidentClient(
            api_base_url="https://example.execute-api.eu-central-1.amazonaws.com/v1",
            session=FakeSession(credentials=False),
        )


def test_synchronizer_contains_no_database_or_sql_client() -> None:
    source = Path("scripts/sync_resolved_incidents.py").read_text(encoding="utf-8").lower()

    assert "psycopg" not in source
    assert "cockroachdb" not in source
    assert "select *" not in source
    assert "insert into" not in source
    assert 'self._url = base + "/incidents"' in source
