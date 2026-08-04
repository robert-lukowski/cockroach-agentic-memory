"""Tests for fail-closed and live dependency wiring."""

from incident_memory.adapters.bedrock import BedrockRuntimeGateway
from incident_memory.adapters.mcp import ManagedMcpIncidentRepository
from incident_memory.bootstrap import build_service
from incident_memory.config import Settings


def test_builds_live_adapters_without_making_calls() -> None:
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

    service = build_service(settings)

    assert isinstance(service._bedrock, BedrockRuntimeGateway)
    assert isinstance(service._repository, ManagedMcpIncidentRepository)
