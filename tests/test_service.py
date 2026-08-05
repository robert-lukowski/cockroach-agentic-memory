"""Unit tests for deterministic RAG orchestration."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from incident_memory.errors import AdapterContractError
from incident_memory.models import (
    EMBEDDING_DIMENSIONS,
    IncidentCreateRequest,
    IncidentEvidence,
    InvestigationRequest,
)
from incident_memory.service import IncidentMemoryService
from tests.fakes import MockBedrockGateway, MockMcpIncidentRepository


def incident_request() -> IncidentCreateRequest:
    return IncidentCreateRequest.from_payload(
        {
            "scope": "hackathon-demo",
            "service": "payments-api",
            "environment": "production",
            "title": "Connection pool exhaustion",
            "symptoms": "Checkout latency rose.",
            "root_cause": "Concurrency exceeded the pool.",
            "resolution": "Bound concurrency and raised the pool limit.",
        }
    )


def test_create_incident_embeds_and_saves() -> None:
    bedrock = MockBedrockGateway()
    repository = MockMcpIncidentRepository()
    fixed_id = UUID("22222222-2222-4222-8222-222222222222")
    fixed_time = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    service = IncidentMemoryService(
        bedrock=bedrock,
        repository=repository,
        id_factory=lambda: fixed_id,
        clock=lambda: fixed_time,
    )

    response = service.create_incident(incident_request())

    assert response.incident_id == fixed_id
    assert response.created_at == fixed_time
    assert response.status == "created"
    assert len(repository.saved) == 1
    assert repository.saved[0].embedding == (0.25,) * EMBEDDING_DIMENSIONS
    assert bedrock.embedding_inputs[0].startswith("Service: payments-api")


def test_source_id_create_is_deterministic_and_repeated_call_is_idempotent() -> None:
    payload = {
        "scope": "servicenow-dev",
        "service": "connect-outbound-orchestrator",
        "environment": "development",
        "title": "Outbound calls stall",
        "symptoms": "Contacts remain pending.",
        "root_cause": "Reserved concurrency was exhausted.",
        "resolution": "Raised concurrency and added alarms.",
        "source_id": "servicenow:demo:00000000000000000000000000000001",
    }
    request = IncidentCreateRequest.from_payload(payload)
    bedrock = MockBedrockGateway()
    repository = MockMcpIncidentRepository()
    service = IncidentMemoryService(bedrock=bedrock, repository=repository)

    created = service.create_incident(request)
    repeated = service.create_incident(request)

    assert created.status == "created"
    assert repeated.status == "already_present"
    assert repeated.incident_id == created.incident_id
    assert len(repository.saved) == 1
    assert len(bedrock.embedding_inputs) == 1


def test_source_id_updates_same_memory_when_relevant_fields_change() -> None:
    original = IncidentCreateRequest.from_payload(
        {
            "scope": "servicenow-dev",
            "service": "connect-outbound-orchestrator",
            "environment": "development",
            "title": "Outbound calls stall",
            "symptoms": "Contacts remain pending.",
            "root_cause": "Reserved concurrency was exhausted.",
            "resolution": "Raised concurrency and added alarms.",
            "source_id": "servicenow:demo:00000000000000000000000000000002",
        }
    )
    changed = replace(original, resolution="Raised concurrency and added a release check.")
    repository = MockMcpIncidentRepository()
    bedrock = MockBedrockGateway()
    service = IncidentMemoryService(bedrock=bedrock, repository=repository)

    created = service.create_incident(original)
    updated = service.create_incident(changed)

    assert updated.status == "updated"
    assert updated.incident_id == created.incident_id
    assert updated.created_at == created.created_at
    assert len(repository.saved) == 1
    assert repository.saved[0].resolution == changed.resolution
    assert len(bedrock.embedding_inputs) == 2


def test_verify_only_reports_absent_and_present_without_embedding_or_write() -> None:
    payload = {
        "scope": "servicenow-dev",
        "service": "connect-outbound-orchestrator",
        "environment": "development",
        "title": "Outbound calls stall",
        "symptoms": "Contacts remain pending.",
        "root_cause": "Reserved concurrency was exhausted.",
        "resolution": "Raised concurrency and added alarms.",
        "source_id": "servicenow:demo:00000000000000000000000000000003",
    }
    request = IncidentCreateRequest.from_payload(payload)
    verify = replace(request, verify_only=True)
    repository = MockMcpIncidentRepository()
    bedrock = MockBedrockGateway()
    service = IncidentMemoryService(bedrock=bedrock, repository=repository)

    absent = service.create_incident(verify)
    created = service.create_incident(request)
    present = service.create_incident(verify)

    assert absent.status == "absent"
    assert absent.created_at is None
    assert created.status == "created"
    assert present.status == "already_present"
    assert len(repository.saved) == 1
    assert len(bedrock.embedding_inputs) == 1


def test_investigation_retrieves_before_generation(evidence) -> None:
    bedrock = MockBedrockGateway(recommendation="Check the connection pool first.")
    repository = MockMcpIncidentRepository(evidence=[evidence])
    service = IncidentMemoryService(bedrock=bedrock, repository=repository)
    request = InvestigationRequest.from_payload(
        {
            "scope": "hackathon-demo",
            "service": "payments-api",
            "environment": "production",
            "symptoms": "Database waits and checkout latency are rising.",
            "top_k": 3,
        }
    )

    response = service.investigate(request)

    assert response.recommendation == "Check the connection pool first."
    assert response.evidence == (evidence,)
    assert repository.search_calls[0]["limit"] == 3
    assert bedrock.generation_calls == [(request.symptoms, (evidence,))]


def test_service_rejects_wrong_embedding_dimensions() -> None:
    bedrock = MockBedrockGateway(embedding=(0.25,) * (EMBEDDING_DIMENSIONS - 1))
    service = IncidentMemoryService(
        bedrock=bedrock,
        repository=MockMcpIncidentRepository(),
    )

    with pytest.raises(AdapterContractError, match="exactly 1024"):
        service.create_incident(incident_request())


@pytest.mark.parametrize("bad_value", [True, float("nan")])
def test_service_rejects_invalid_embedding_values(bad_value: object) -> None:
    embedding = [0.25] * EMBEDDING_DIMENSIONS
    embedding[0] = bad_value
    bedrock = MockBedrockGateway(embedding=tuple(embedding))
    service = IncidentMemoryService(
        bedrock=bedrock,
        repository=MockMcpIncidentRepository(),
    )

    with pytest.raises(AdapterContractError, match="embedding adapter"):
        service.create_incident(incident_request())


def test_service_rejects_empty_recommendation() -> None:
    service = IncidentMemoryService(
        bedrock=MockBedrockGateway(recommendation="  "),
        repository=MockMcpIncidentRepository(),
    )
    request = InvestigationRequest.from_payload(
        {"scope": "hackathon-demo", "symptoms": "Latency is rising."}
    )

    with pytest.raises(AdapterContractError, match="empty recommendation"):
        service.investigate(request)


def test_service_rejects_cross_scope_evidence(evidence) -> None:
    cross_scope_evidence = IncidentEvidence(
        incident=replace(evidence.incident, scope="another-scope"),
        similarity=evidence.similarity,
    )

    class CrossScopeRepository(MockMcpIncidentRepository):
        def find_similar(self, **kwargs):
            del kwargs
            return [cross_scope_evidence]

    service = IncidentMemoryService(
        bedrock=MockBedrockGateway(),
        repository=CrossScopeRepository(),
    )
    request = InvestigationRequest.from_payload(
        {"scope": "hackathon-demo", "symptoms": "Latency is rising."}
    )

    with pytest.raises(AdapterContractError, match="another scope"):
        service.investigate(request)
