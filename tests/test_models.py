"""Unit tests for request validation."""

import pytest

from incident_memory.errors import ValidationError
from incident_memory.models import IncidentCreateRequest, InvestigationRequest


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
