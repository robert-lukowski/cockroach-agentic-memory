"""Unit tests for request validation."""

import pytest

from incident_memory.errors import ValidationError
from incident_memory.models import (
    IncidentCreateRequest,
    InvestigationRequest,
    ServiceNowAnalyzeRequest,
)


def valid_incident_payload() -> dict[str, object]:
    return {
        "scope": "hackathon-demo",
        "service": "payments-api",
        "environment": "production",
        "title": "Connection pool exhaustion",
        "symptoms": "Checkout latency rose.",
        "root_cause": "Concurrency exceeded the connection pool.",
        "resolution": "Bound concurrency and raised the pool limit.",
        "tags": ["database", "database", "latency"],
        "metadata": {"severity": "SEV-2"},
    }


def valid_servicenow_payload() -> dict[str, object]:
    return {
        "incident_sys_id": "0123456789abcdef0123456789abcdef",
        "number": "INC0012345",
        "short_description": "Checkout requests are timing out",
        "description": "Database waits rose after a traffic increase.",
        "category": "Software",
        "subcategory": "Database",
        "priority": "2 - High",
        "impact": "2 - Medium",
        "urgency": "1 - High",
        "assignment_group": "Payments SRE",
        "cmdb_ci": "payments-api",
        "opened_at": "2026-08-05 10:00:00",
    }


def test_incident_request_normalizes_values() -> None:
    payload = valid_incident_payload()
    payload["service"] = "  payments-api  "

    request = IncidentCreateRequest.from_payload(payload)

    assert request.service == "payments-api"
    assert request.tags == ("database", "latency")
    assert "Root cause: Concurrency exceeded" in request.embedding_text()


@pytest.mark.parametrize("field", ["scope", "service", "symptoms", "resolution"])
def test_incident_request_rejects_missing_required_field(field: str) -> None:
    payload = valid_incident_payload()
    del payload[field]

    with pytest.raises(ValidationError, match="missing"):
        IncidentCreateRequest.from_payload(payload)


def test_incident_request_rejects_unexpected_fields() -> None:
    payload = valid_incident_payload()
    payload["sql"] = "SELECT * FROM secrets"

    with pytest.raises(ValidationError, match="unsupported"):
        IncidentCreateRequest.from_payload(payload)


def test_incident_request_normalizes_source_id_into_metadata() -> None:
    payload = valid_incident_payload()
    payload["source_id"] = "servicenow:demo:00000000000000000000000000000001"

    request = IncidentCreateRequest.from_payload(payload)

    assert request.source_id == payload["source_id"]
    assert request.metadata["source_id"] == payload["source_id"]
    assert request.verify_only is False


@pytest.mark.parametrize(
    "payload_update",
    [
        {"source_id": "unsafe source id"},
        {"verify_only": True},
        {
            "source_id": "servicenow:demo:00000000000000000000000000000001",
            "metadata": {"source_id": "servicenow:demo:different"},
        },
        {"verify_only": "true"},
    ],
)
def test_incident_request_rejects_invalid_idempotency_fields(payload_update) -> None:
    payload = valid_incident_payload()
    payload.update(payload_update)

    with pytest.raises(ValidationError):
        IncidentCreateRequest.from_payload(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("service", " ", "non-empty"),
        ("tags", "database", "array"),
        ("tags", [""], "Each tag"),
        ("metadata", [], "JSON object"),
    ],
)
def test_incident_request_rejects_invalid_field_types(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = valid_incident_payload()
    payload[field] = value

    with pytest.raises(ValidationError, match=message):
        IncidentCreateRequest.from_payload(payload)


def test_request_body_must_be_an_object() -> None:
    with pytest.raises(ValidationError, match="JSON object"):
        IncidentCreateRequest.from_payload([])


def test_investigation_rejects_empty_optional_filter() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        InvestigationRequest.from_payload(
            {"scope": "hackathon-demo", "symptoms": "Latency", "service": ""}
        )


@pytest.mark.parametrize("top_k", [0, 11, True, "5"])
def test_investigation_request_rejects_invalid_top_k(top_k: object) -> None:
    with pytest.raises(ValidationError, match="top_k"):
        InvestigationRequest.from_payload(
            {"scope": "hackathon-demo", "symptoms": "Latency is rising", "top_k": top_k}
        )


def test_servicenow_request_maps_to_server_scoped_investigation() -> None:
    request = ServiceNowAnalyzeRequest.from_payload(valid_servicenow_payload())

    investigation = request.as_investigation(scope="servicenow-dev")

    assert investigation.scope == "servicenow-dev"
    assert investigation.service is None
    assert investigation.environment is None
    assert investigation.top_k == 5
    assert "Short description: Checkout requests are timing out" in investigation.symptoms
    assert "Description: Database waits rose" in investigation.symptoms
    assert request.incident_sys_id not in investigation.symptoms


@pytest.mark.parametrize("field", ["incident_sys_id", "number", "short_description", "opened_at"])
def test_servicenow_request_rejects_missing_fields(field: str) -> None:
    payload = valid_servicenow_payload()
    del payload[field]

    with pytest.raises(ValidationError, match="missing"):
        ServiceNowAnalyzeRequest.from_payload(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("incident_sys_id", "not-a-sys-id", "32-character hexadecimal"),
        ("number", "", "non-empty"),
        ("short_description", 42, "must be a string"),
        ("description", "x" * 8_001, "at most 8000"),
    ],
)
def test_servicenow_request_rejects_invalid_values(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = valid_servicenow_payload()
    payload[field] = value

    with pytest.raises(ValidationError, match=message):
        ServiceNowAnalyzeRequest.from_payload(payload)


def test_servicenow_request_rejects_unknown_fields() -> None:
    payload = valid_servicenow_payload()
    payload["sql"] = "SELECT 1"

    with pytest.raises(ValidationError, match="unsupported"):
        ServiceNowAnalyzeRequest.from_payload(payload)
