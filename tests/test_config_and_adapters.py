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
        adapter.find_by_id(stored_incident.incident_id)
    with pytest.raises(DependencyUnavailableError, match="repository"):
        adapter.find_similar(
            scope="hackathon-demo",
            embedding=stored_incident.embedding,
            limit=5,
            service=None,
            environment=None,
        )


def test_live_configuration_enables_live_adapters_without_exposing_values() -> None:
    settings = Settings.from_environment(
        {
            "APP_MODE": "live",
            "EMBEDDING_DIMENSIONS": "1024",
            "BEDROCK_EMBEDDING_MODEL_ID": "embedding-model",
            "BEDROCK_GENERATION_MODEL_ID": "generation-model",
            "MCP_SECRET_ARN": "arn:aws:secretsmanager:eu-central-1:123456789012:secret:mcp",
            "COCKROACH_CLUSTER_ID": "11111111-1111-4111-8111-111111111111",
            "REPOSITORY_BACKEND": "managed-mcp",
        }
    )

    health = settings.health_payload()

    assert settings.live_adapters_enabled is True
    assert health["configuration"]["live_adapters_enabled"] is True
    assert "11111111" not in str(health)
    assert "arn:aws:secretsmanager" not in str(health)


def test_live_configuration_reports_missing_required_values() -> None:
    settings = Settings.from_environment({"APP_MODE": "live"})

    assert settings.live_adapters_enabled is False
    assert len(settings.issues) == 4


def test_invalid_servicenow_scope_fails_configuration_closed() -> None:
    settings = Settings.from_environment({"SERVICENOW_MEMORY_SCOPE": "invalid scope"})

    assert settings.live_adapters_enabled is False
    assert any("SERVICENOW_MEMORY_SCOPE" in issue for issue in settings.issues)
