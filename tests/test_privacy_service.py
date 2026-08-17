"""End-to-end service tests for privacy redaction before retrieval and generation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from incident_memory.models import InvestigationRequest
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
            root_cause=f"Customer email {raw_email} appeared in the diagnostic payload.",
            resolution=f"Phone: {raw_phone}\nRemoved the direct identifier from the payload.",
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
    for forbidden in (raw_name, raw_email, raw_phone):
        assert forbidden not in embedding_text
        assert forbidden not in generation_text
        assert forbidden not in audited_text
        assert forbidden not in generation_evidence[0].incident.root_cause
        assert forbidden not in generation_evidence[0].incident.resolution
        assert forbidden not in str(response.as_servicenow_dict())

    assert "[REDACTED_EMAIL]" in embedding_text
    assert "[REDACTED_PHONE]" in embedding_text
    assert "[REDACTED_NAME]" in embedding_text
    assert response.timings.keys() >= {
        "privacy_guard_ms",
        "vector_retrieval_ms",
        "bedrock_inference_ms",
        "total_request_ms",
    }


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
