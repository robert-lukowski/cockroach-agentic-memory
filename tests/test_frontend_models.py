"""Tests for frontend request mapping and response normalization."""

from datetime import UTC, datetime

import pytest

from frontend.models import (
    InputValidationError,
    InvestigationInput,
    ResponseValidationError,
    format_milliseconds,
    format_percentage,
    normalize_analysis_response,
)

INCIDENT_ID = "11111111-1111-4111-8111-111111111111"


def rich_response() -> dict[str, object]:
    return {
        "recommendation": (
            "Diagnosis:\nCapacity is constrained.\n\nRecommended actions:\n1. Check limits."
        ),
        "confidence": 0.91,
        "timings": {
            "retrieval_ms": 125.4,
            "generation_ms": 820.0,
            "total_ms": 1_050.0,
            "unknown_ms": 7,
        },
        "supporting_incidents": [
            {
                "incident_id": INCIDENT_ID,
                "incident_number": "INC9000016",
                "service": "Authentication Service",
                "similarity": 0.942,
                "root_cause": "A synthetic policy change removed access.",
                "resolution": "Restored the required scoped permission.",
                "metadata": {"must_not_be_exposed": True},
            },
            {
                "incident_id": "22222222-2222-4222-8222-222222222222",
                "incident_number": "INC9000017",
                "service": "Authentication Service",
                "similarity": 0.71,
                "root_cause": "A synthetic cache entry expired.",
                "resolution": "Refreshed the safe configuration.",
            },
        ],
        "supporting_incident_ids": [INCIDENT_ID],
        "unexpected": "ignored",
    }


def test_normalizes_rich_supporting_incidents_and_timings() -> None:
    result = normalize_analysis_response(rich_response())

    assert result.confidence == 0.91
    assert result.best_similarity == 0.942
    assert result.supporting_count == 2
    assert result.supporting_evidence_reported is True
    assert result.timings == {
        "vector_retrieval_ms": 125.4,
        "bedrock_inference_ms": 820.0,
        "total_request_ms": 1_050.0,
    }
    assert [item.incident_number for item in result.supporting_incidents] == [
        "INC9000016",
        "INC9000017",
    ]
    assert not hasattr(result.supporting_incidents[0], "metadata")


def test_rich_incidents_are_ordered_by_similarity_descending() -> None:
    payload = rich_response()
    payload["supporting_incidents"].reverse()

    result = normalize_analysis_response(payload)

    assert [item.similarity for item in result.supporting_incidents] == [0.942, 0.71]


def test_legacy_supporting_incident_ids_are_preserved_as_fallback() -> None:
    result = normalize_analysis_response(
        {
            "recommendation": "Inspect the matching operational memory.",
            "supporting_incident_ids": [INCIDENT_ID, "", None],
        }
    )

    assert result.supporting_incidents == ()
    assert result.legacy_incident_ids == (INCIDENT_ID,)
    assert result.supporting_count == 1
    assert result.supporting_evidence_reported is True


def test_missing_confidence_and_timings_remain_unavailable() -> None:
    result = normalize_analysis_response(
        {"recommendation": "Inspect the matching operational memory."}
    )

    assert result.confidence is None
    assert result.timings == {}
    assert result.best_similarity is None
    assert result.supporting_evidence_reported is False
    assert format_percentage(result.confidence) == "Not available"
    assert format_milliseconds(result.timings.get("total_request_ms")) == "Not available"


def test_incident_number_is_preferred_over_uuid() -> None:
    result = normalize_analysis_response(rich_response())

    assert result.supporting_incidents[0].display_identifier == "INC9000016"
    assert result.supporting_incidents[0].display_identifier != INCIDENT_ID


def test_incomplete_optional_supporting_fields_do_not_fail_response() -> None:
    result = normalize_analysis_response(
        {
            "recommendation": "Continue with scoped diagnostics.",
            "supporting_incidents": [
                {
                    "incident_id": INCIDENT_ID,
                    "incident_number": None,
                    "service": "",
                    "similarity": "unknown",
                },
                "invalid-entry",
            ],
        }
    )

    incident = result.supporting_incidents[0]
    assert incident.display_identifier == INCIDENT_ID
    assert incident.service == "unknown"
    assert incident.similarity is None
    assert incident.root_cause == ""
    assert incident.resolution == ""


@pytest.mark.parametrize("payload", [None, [], {}, {"recommendation": "  "}])
def test_invalid_or_incomplete_response_is_rejected(payload) -> None:
    with pytest.raises(ResponseValidationError):
        normalize_analysis_response(payload)


def test_form_maps_to_existing_servicenow_contract() -> None:
    payload = InvestigationInput(
        title="Synthetic incident",
        symptoms="A synthetic request times out.",
        service="demo-service",
        environment="development",
    ).to_api_payload(
        incident_sys_id="0123456789abcdef0123456789abcdef",
        opened_at=datetime(2026, 8, 6, 10, 30, tzinfo=UTC),
    )

    assert set(payload) == {
        "incident_sys_id",
        "number",
        "short_description",
        "description",
        "category",
        "subcategory",
        "priority",
        "impact",
        "urgency",
        "assignment_group",
        "cmdb_ci",
        "opened_at",
    }
    assert payload["number"] == "DEMO-01234567"
    assert payload["short_description"] == "Synthetic incident"
    assert payload["description"].endswith("Environment: development")
    assert payload["cmdb_ci"] == "demo-service"


@pytest.mark.parametrize(
    ("title", "symptoms"),
    [("", "Synthetic symptoms"), ("Synthetic title", "")],
)
def test_form_rejects_missing_required_fields(title: str, symptoms: str) -> None:
    with pytest.raises(InputValidationError):
        InvestigationInput(title=title, symptoms=symptoms).to_api_payload()
