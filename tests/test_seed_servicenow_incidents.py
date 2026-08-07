"""Tests for safe, idempotent ServiceNow demo seeding."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts.seed_servicenow_incidents import (
    STATE_MAPPING,
    SYNTHETIC_MARKER,
    ConfigurationError,
    HttpResponse,
    ServiceNowClient,
    ServiceNowError,
    build_incident_payload,
    configuration_from_environment,
    resolve_incident_classifications,
    seed_records,
    select_demo_close_code,
    select_records,
    validate_state_mapping,
)

DATASET = json.loads(Path("data/servicenow_demo_incidents.json").read_text(encoding="utf-8"))
GROUP_ID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
CI_ID = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
INCIDENT_ID = "cccccccccccccccccccccccccccccccc"


class FakeServiceNowClient:
    def __init__(self) -> None:
        self.references: dict[tuple[str, str], str] = {}
        self.incidents: dict[str, list[dict[str, Any]]] = {}
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[str, dict[str, Any]]] = []
        self.state_mapping = dict(STATE_MAPPING)
        self.close_code_choices = [
            {"label": "Known error", "value": "known_error"},
            {"label": "Solution provided", "value": "solution_provided"},
        ]
        self.category_choices = [
            {"label": "Inquiry / Help", "value": "inquiry"},
            {"label": "Database", "value": "database"},
        ]
        self.subcategory_choices = [
            {"label": "DB2", "value": "db2", "dependent_value": "database"},
        ]

    def list_records(self, table, *, query, fields, limit=100):
        del fields, limit
        if table == "sys_dictionary":
            assert query == "name=task^element=state"
            return [{"name": "task", "element": "state", "internal_type": "integer"}]
        if table == "sys_choice":
            if "element=close_code" in query:
                return deepcopy(self.close_code_choices)
            if "element=category" in query:
                return deepcopy(self.category_choices)
            if "element=subcategory" in query:
                return deepcopy(self.subcategory_choices)
            return [
                {"label": label, "value": value}
                for label, value in self.state_mapping.items()
            ]
        field, value = query.split("=", maxsplit=1)
        assert field == "name" if table in {"sys_user_group", "cmdb_ci"} else "number"
        if table in {"sys_user_group", "cmdb_ci"}:
            sys_id = self.references.get((table, value))
            return [] if sys_id is None else [{"sys_id": sys_id, "name": value}]
        return deepcopy(self.incidents.get(value, []))

    def create_incident(self, payload):
        self.created.append(deepcopy(payload))

    def update_incident(self, sys_id, payload):
        self.updated.append((sys_id, deepcopy(payload)))


class FakeTransport:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _references(client: FakeServiceNowClient, record: dict[str, Any]) -> None:
    client.references[("sys_user_group", record["assignment_group"])] = GROUP_ID
    client.references[("cmdb_ci", record["cmdb_ci"])] = CI_ID


def test_missing_configuration_lists_names_without_values() -> None:
    with pytest.raises(ConfigurationError) as captured:
        configuration_from_environment({"SERVICENOW_USERNAME": "demo-user"})

    message = str(captured.value)
    assert "SERVICENOW_INSTANCE_URL" in message
    assert "SERVICENOW_PASSWORD" in message
    assert "demo-user" not in message


def test_dataset_filtering_and_limit() -> None:
    active, skipped_active = select_records(
        DATASET,
        only_active=True,
        only_resolved=False,
        limit=4,
    )
    resolved, skipped_resolved = select_records(
        DATASET,
        only_active=False,
        only_resolved=True,
        limit=None,
    )

    assert len(active) == 4
    assert all(record["active"] for record in active)
    assert skipped_active == 56
    assert len(resolved) == 50
    assert all(not record["active"] for record in resolved)
    assert skipped_resolved == 10


def test_state_mapping_is_validated_against_pdi_choices() -> None:
    client = FakeServiceNowClient()
    validate_state_mapping(client)
    client.state_mapping["Resolved"] = "9"

    with pytest.raises(ConfigurationError, match="Resolved"):
        validate_state_mapping(client)


def test_demo_close_code_uses_valid_preferred_pdi_choice() -> None:
    client = FakeServiceNowClient()

    assert select_demo_close_code(client) == (
        "Solution provided",
        "solution_provided",
    )


def test_classifications_use_active_pdi_values_and_generic_fallback() -> None:
    client = FakeServiceNowClient()

    classifications = resolve_incident_classifications(
        client,
        [DATASET[0], DATASET[27]],
    )

    assert classifications["INC9000001"] == ("inquiry", "")
    assert classifications["INC9000028"] == ("database", "")


def test_resolved_payload_uses_pdi_close_code_without_changing_resolution() -> None:
    record = deepcopy(DATASET[0])

    payload = build_incident_payload(
        record,
        assignment_group_id=None,
        cmdb_ci_id=None,
        close_code_value="solution_provided",
    )

    assert payload["close_code"] == "solution_provided"
    assert record["root_cause"] in payload["close_notes"]
    assert record["resolution"] in payload["close_notes"]
    assert record["close_notes"] in payload["close_notes"]
    assert "priority" not in payload


def test_create_update_and_unchanged_behavior() -> None:
    records = deepcopy(DATASET[:3])
    client = FakeServiceNowClient()
    for record in records:
        _references(client, record)
    unchanged_payload = build_incident_payload(
        records[0], assignment_group_id=GROUP_ID, cmdb_ci_id=CI_ID
    )
    client.incidents[records[0]["number"]] = [{"sys_id": INCIDENT_ID, **unchanged_payload}]
    client.incidents[records[1]["number"]] = [
        {"sys_id": INCIDENT_ID, "number": records[1]["number"]}
    ]

    summary = seed_records(records, client=client, warning=lambda _: None)

    assert summary.unchanged == 1
    assert summary.updated == 1
    assert summary.created == 1
    assert summary.failed == 0
    assert len(client.updated) == 1
    assert len(client.created) == 1
    assert json.dumps(client.created[0]).count(SYNTHETIC_MARKER) == 1


def test_terminal_resolved_and_closed_states_are_idempotent() -> None:
    record = deepcopy(DATASET[0])
    client = FakeServiceNowClient()
    desired = build_incident_payload(
        record,
        assignment_group_id=None,
        cmdb_ci_id=None,
        category_value="inquiry",
        subcategory_value="",
    )
    client.incidents[record["number"]] = [
        {"sys_id": INCIDENT_ID, **desired, "state": STATE_MAPPING["Closed"]}
    ]

    summary = seed_records(
        [record],
        client=client,
        classification_values={record["number"]: ("inquiry", "")},
    )

    assert summary.unchanged == 1
    assert summary.updated == 0


def test_duplicate_incident_number_fails_without_write() -> None:
    record = deepcopy(DATASET[0])
    client = FakeServiceNowClient()
    _references(client, record)
    client.incidents[record["number"]] = [
        {"sys_id": INCIDENT_ID},
        {"sys_id": "dddddddddddddddddddddddddddddddd"},
    ]
    warnings: list[str] = []

    summary = seed_records([record], client=client, warning=warnings.append)

    assert summary.failed == 1
    assert not client.created
    assert not client.updated
    assert "duplicate incident number" in warnings[0]


def test_reference_resolution_and_missing_reference_behavior() -> None:
    record = deepcopy(DATASET[0])
    client = FakeServiceNowClient()
    client.references[("sys_user_group", record["assignment_group"])] = GROUP_ID

    summary = seed_records([record], client=client, warning=lambda _: None)

    assert summary.missing_assignment_group_reference == 0
    assert summary.missing_cmdb_ci_reference == 1
    assert client.created[0]["assignment_group"] == GROUP_ID
    assert client.created[0]["cmdb_ci"] == ""


def test_active_payload_has_marker_but_no_resolution_fields() -> None:
    payload = build_incident_payload(
        DATASET[2], assignment_group_id=None, cmdb_ci_id=None
    )

    assert json.dumps(payload).count(SYNTHETIC_MARKER) == 1
    for field in ("resolved_at", "close_code", "close_notes", "root_cause", "resolution"):
        assert field not in payload


def test_every_dataset_payload_contains_one_synthetic_marker() -> None:
    for record in DATASET:
        payload = build_incident_payload(
            record,
            assignment_group_id=None,
            cmdb_ci_id=None,
            close_code_value="solution_provided" if not record["active"] else None,
        )

        assert json.dumps(payload).count(SYNTHETIC_MARKER) == 1


def test_retry_is_bounded_to_429_and_transient_5xx() -> None:
    transport = FakeTransport(
        [
            HttpResponse(429, b"provider detail"),
            HttpResponse(503, b"provider detail"),
            HttpResponse(200, b'{"result":[]}'),
        ]
    )
    sleeps: list[float] = []
    client = ServiceNowClient(
        instance_url="https://fictional.service-now.example",
        username="demo-user",
        password="demo-password",
        transport=transport,
        sleep=sleeps.append,
    )

    assert client.list_records("incident", query="number=INC9000001", fields=("sys_id",)) == []
    assert len(transport.calls) == 3
    assert sleeps == [1.0, 2.0]
    assert all(call["timeout"] == 20.0 for call in transport.calls)


@pytest.mark.parametrize("status", [400, 401, 403])
def test_nonretryable_failures_are_safe(status: int) -> None:
    transport = FakeTransport([HttpResponse(status, b"demo-password provider detail")])
    client = ServiceNowClient(
        instance_url="https://fictional.service-now.example",
        username="demo-user",
        password="demo-password",
        transport=transport,
    )

    with pytest.raises(ServiceNowError) as captured:
        client.list_records("incident", query="number=INC9000001", fields=("sys_id",))

    assert len(transport.calls) == 1
    assert "demo-password" not in str(captured.value)
    assert "provider detail" not in str(captured.value)
