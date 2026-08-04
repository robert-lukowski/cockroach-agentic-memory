"""Tests for secret-safe configuration and fail-closed scaffold adapters."""

import pytest

from incident_memory.adapters.unavailable import (
    UnavailableBedrockGateway,
    UnavailableIncidentRepository,
)
from incident_memory.config import Settings
from incident_memory.errors import DependencyUnavailableError


@pytest.mark.parametrize("raw_dimensions", ["invalid", "512"])
def test_invalid_embedding_configuration_reports_degraded_status(raw_dimensions: str) -> None:
    settings = Settings.from_environment({"EMBEDDING_DIMENSIONS": raw_dimensions})

    health = settings.health_payload()

    assert health["status"] == "degraded"
    assert health["configuration"]["valid"] is False
    assert health["configuration"]["issues"]


def test_unavailable_bedrock_gateway_fails_closed() -> None:
    adapter = UnavailableBedrockGateway()

    with pytest.raises(DependencyUnavailableError, match="Bedrock"):
        adapter.generate_recommendation(symptoms="Latency", evidence=[])


def test_unavailable_repository_fails_closed(stored_incident) -> None:
    adapter = UnavailableIncidentRepository()

    with pytest.raises(DependencyUnavailableError, match="repository"):
        adapter.save(stored_incident)
    with pytest.raises(DependencyUnavailableError, match="repository"):
        adapter.find_similar(
            scope="hackathon-demo",
            embedding=stored_incident.embedding,
            limit=5,
            service=None,
            environment=None,
        )
