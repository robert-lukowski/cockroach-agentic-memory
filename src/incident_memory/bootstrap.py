"""Dependency wiring for scaffold and approved live modes."""

from incident_memory.adapters.bedrock import BedrockRuntimeGateway
from incident_memory.adapters.mcp import ManagedMcpIncidentRepository, ManagedMcpToolClient
from incident_memory.adapters.secrets import SecretsManagerApiKeyProvider
from incident_memory.adapters.unavailable import (
    UnavailableBedrockGateway,
    UnavailableIncidentRepository,
)
from incident_memory.config import Settings
from incident_memory.service import IncidentMemoryService


def build_service(settings: Settings) -> IncidentMemoryService:
    if not settings.live_adapters_enabled:
        return IncidentMemoryService(
            bedrock=UnavailableBedrockGateway(),
            repository=UnavailableIncidentRepository(),
        )

    api_key_provider = SecretsManagerApiKeyProvider(
        secret_arn=settings.mcp_secret_arn,
        region=settings.aws_region,
    )
    tool_client = ManagedMcpToolClient(
        url=settings.mcp_url,
        cluster_id=settings.cockroach_cluster_id,
        api_key_provider=api_key_provider,
    )
    repository = ManagedMcpIncidentRepository(
        tool_caller=tool_client,
        database=settings.cockroach_database,
    )
    bedrock = BedrockRuntimeGateway(
        region=settings.aws_region,
        embedding_model_id=settings.embedding_model_id,
        generation_model_id=settings.generation_model_id,
    )
    return IncidentMemoryService(bedrock=bedrock, repository=repository)
