"""Fail-closed adapters used until live integrations are approved."""

from collections.abc import Sequence

from incident_memory.errors import DependencyUnavailableError
from incident_memory.models import IncidentEvidence, StoredIncident


class UnavailableBedrockGateway:
    """Prevents accidental Bedrock calls during the scaffold phase."""

    def generate_embedding(self, text: str) -> Sequence[float]:
        del text
        raise DependencyUnavailableError("Bedrock")

    def generate_recommendation(
        self,
        *,
        symptoms: str,
        evidence: Sequence[IncidentEvidence],
    ) -> str:
        del symptoms, evidence
        raise DependencyUnavailableError("Bedrock")


class UnavailableIncidentRepository:
    """Prevents accidental CockroachDB or MCP calls during the scaffold phase."""

    def save(self, incident: StoredIncident) -> None:
        del incident
        raise DependencyUnavailableError("incident repository")

    def find_similar(
        self,
        *,
        scope: str,
        embedding: Sequence[float],
        limit: int,
        service: str | None,
        environment: str | None,
    ) -> Sequence[IncidentEvidence]:
        del scope, embedding, limit, service, environment
        raise DependencyUnavailableError("incident repository")
