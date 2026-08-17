"""End-to-end service tests for privacy redaction before retrieval and generation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pytest

from incident_memory.errors import ValidationError
from incident_memory.models import IncidentCreateRequest, InvestigationRequest
from incident_memory.service import IncidentMemoryService
from tests.fakes import MockBedrockGateway, MockMcpIncidentRepository


@dataclass
class PassingPrivacyAuditor:
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    def audit_privacy(self, *, text: str, categories: tuple[str, ...]) -> str:
        self.calls.append((text, categories))
        return "PASS"


def test_investigation_redacts_before_embedding_and_generation(evidence) -> None:
    raw_email = "alex.morgan@example.invalid"
    raw_phone = "+1 202-555-0147"
    raw_name = "Alex Morgan"
    request = InvestigationRequest.from_payload(
        {
            "scope": "hackathon-demo",
            "symptoms": (
                "Notification retries fail after deployment.\n"
                f"Name: {raw_name}\n"
                f"Email: {raw_email}\n"
                f"Phone: {raw_phone}"
            ),
        }
    )
    evidence_with_pii = replace(
        evidence,
        incident=replace(
            evidence.incident,
            service=raw_email,
            environment=f"Phone: {raw_phone}",
            root_cause=f"Customer email {raw_email} appeared in the diagnostic payload.",
            resolution=f"Phone: {raw_phone}\nRemoved the direct identifier from the payload.",
            tags=(raw_email, f"Phone: {raw_phone}"),
            metadata={
                **evidence.incident.metadata,
                "contact_name": raw_name,
                "nested": {
                    "phone": raw_phone,
                    "owner": raw_email,
                },
            },
        ),
    )
    bedrock = MockBedrockGateway(recommendation="Use the validated historical remediation.")
    repository = MockMcpIncidentRepository(evidence=[evidence_with_pii])
    auditor = PassingPrivacyAuditor()
    service = IncidentMemoryService(
        bedrock=bedrock,
        repository=repository,
        privacy_auditor=auditor,
    )

    response = service.investigate(request)

    assert response.privacy_guard.status == "verified"
    assert response.privacy_guard.redactions == 3
    assert response.privacy_guard.ai_reviewed is True

    embedding_text = bedrock.embedding_inputs[0]
    generation_text, generation_evidence = bedrock.generation_calls[0]
    audited_text, _categories = auditor.calls[0]
    projected = str(response.as_servicenow_dict())
    protected_incident = generation_evidence[0].incident
    for forbidden in (raw_name, raw_email, raw_phone):
        assert forbidden not in embedding_text
        assert forbidden not in generation_text
        assert forbidden not in audited_text
        assert forbidden not in str(protected_incident)
        assert forbidden not in projected

    assert protected_incident.service == "[REDACTED_EMAIL]"
    assert "[REDACTED_PHONE]" in protected_incident.environment
    assert protected_incident.metadata["contact_name"] == "[REDACTED_NAME]"
    assert protected_incident.metadata["nested"]["phone"] == "[REDACTED_PHONE]"
    assert protected_incident.metadata["nested"]["owner"] == "[REDACTED_EMAIL]"
    assert "[REDACTED_EMAIL]" in embedding_text
    assert "[REDACTED_PHONE]" in embedding_text
    assert "[REDACTED_NAME]" in embedding_text
    assert response.timings.keys() >= {
        "privacy_guard_ms",
        "vector_retrieval_ms",
        "bedrock_inference_ms",
        "total_request_ms",
    }


def test_create_incident_redacts_all_embedded_and_persisted_text_fields() -> None:
    raw_email = "alex.morgan@example.invalid"
    raw_phone = "+1 202-555-0147"
    raw_name = "Alex Morgan"
    request = IncidentCreateRequest.from_payload(
        {
            "scope": "hackathon-demo",
            "service": raw_email,
            "environment": f"Phone: {raw_phone}",
            "title": "Notification worker retries",
            "symptoms": "Retries rise after deployment.",
            "root_cause": "A malformed customer notification entered the retry path.",
            "resolution": "Validated the notification payload before dispatch.",
            "tags": [raw_email, raw_phone],
            "metadata": {
                "contact_name": raw_name,
                "owner": raw_email,
                "nested": {
                    "phone": raw_phone,
                    "contacts": [raw_email, raw_phone],
                },
            },
        }
    )
    bedrock = MockBedrockGateway()
    repository = MockMcpIncidentRepository()
    service = IncidentMemoryService(bedrock=bedrock, repository=repository)

    response = service.create_incident(request)

    assert response.status == "created"
    assert repository.saved
    stored = repository.saved[0]
    embedding_text = bedrock.embedding_inputs[0]
    for forbidden in (raw_name, raw_email, raw_phone):
        assert forbidden not in embedding_text
        assert forbidden not in str(stored)

    assert stored.service == "[REDACTED_EMAIL]"
    assert "[REDACTED_PHONE]" in stored.environment
    assert stored.tags == ("[REDACTED_EMAIL]", "[REDACTED_PHONE]")
    assert stored.metadata["contact_name"] == "[REDACTED_NAME]"
    assert stored.metadata["owner"] == "[REDACTED_EMAIL]"
    assert stored.metadata["nested"]["phone"] == "[REDACTED_PHONE]"
    assert stored.metadata["nested"]["contacts"] == [
        "[REDACTED_EMAIL]",
        "[REDACTED_PHONE]",
    ]


def test_create_incident_rejects_direct_identifier_in_metadata_key() -> None:
    request = IncidentCreateRequest.from_payload(
        {
            "scope": "hackathon-demo",
            "service": "notification-orchestrator",
            "environment": "development",
            "title": "Notification worker retries",
            "symptoms": "Retries rise after deployment.",
            "root_cause": "Malformed notification payload.",
            "resolution": "Validated payload before dispatch.",
            "metadata": {"alex.morgan@example.invalid": "owner"},
        }
    )
    bedrock = MockBedrockGateway()
    repository = MockMcpIncidentRepository()
    service = IncidentMemoryService(bedrock=bedrock, repository=repository)

    with pytest.raises(ValidationError) as exc_info:
        service.create_incident(request)

    assert exc_info.value.details == {"field": "metadata"}
    assert bedrock.embedding_inputs == []
    assert repository.saved == []


def test_clean_investigation_keeps_existing_behavior_without_secondary_audit(evidence) -> None:
    bedrock = MockBedrockGateway()
    repository = MockMcpIncidentRepository(evidence=[evidence])
    auditor = PassingPrivacyAuditor()
    service = IncidentMemoryService(
        bedrock=bedrock,
        repository=repository,
        privacy_auditor=auditor,
    )
    request = InvestigationRequest.from_payload(
        {"scope": "hackathon-demo", "symptoms": "Database waits are rising."}
    )

    response = service.investigate(request)

    assert response.privacy_guard.status == "not_required"
    assert response.privacy_guard.redactions == 0
    assert auditor.calls == []
    assert bedrock.generation_calls[0][0] == request.symptoms
