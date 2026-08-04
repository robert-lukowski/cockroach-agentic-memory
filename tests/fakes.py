"""Deterministic test adapters with no network or credential access."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from incident_memory.models import EMBEDDING_DIMENSIONS, IncidentEvidence, StoredIncident


@dataclass
class MockBedrockGateway:
    """Records Bedrock port calls and returns deterministic values."""

    recommendation: str = "Review connection pool saturation and concurrency limits."
    embedding: tuple[float, ...] = (0.25,) * EMBEDDING_DIMENSIONS
    embedding_inputs: list[str] = field(default_factory=list)
    generation_calls: list[tuple[str, tuple[IncidentEvidence, ...]]] = field(default_factory=list)

    def generate_embedding(self, text: str) -> Sequence[float]:
        self.embedding_inputs.append(text)
        return self.embedding

    def generate_recommendation(
        self,
        *,
        symptoms: str,
        evidence: Sequence[IncidentEvidence],
    ) -> str:
        self.generation_calls.append((symptoms, tuple(evidence)))
        return self.recommendation


@dataclass
class MockMcpIncidentRepository:
    """MCP-shaped repository fake exposing only the approved repository operations."""

    evidence: list[IncidentEvidence] = field(default_factory=list)
    saved: list[StoredIncident] = field(default_factory=list)
    search_calls: list[dict[str, object]] = field(default_factory=list)

    def save(self, incident: StoredIncident) -> None:
        self.saved.append(incident)

    def find_similar(
        self,
        *,
        scope: str,
        embedding: Sequence[float],
        limit: int,
        service: str | None,
        environment: str | None,
    ) -> Sequence[IncidentEvidence]:
        self.search_calls.append(
            {
                "scope": scope,
                "embedding": tuple(embedding),
                "limit": limit,
                "service": service,
                "environment": environment,
            }
        )
        matches = [
            item
            for item in self.evidence
            if item.incident.scope == scope
            and (service is None or item.incident.service == service)
            and (environment is None or item.incident.environment == environment)
        ]
        return matches[:limit]
