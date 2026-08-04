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
    assert len(repository.saved) == 1
    assert repository.saved[0].embedding == (0.25,) * EMBEDDING_DIMENSIONS
    assert bedrock.embedding_inputs[0].startswith("Service: payments-api")


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
