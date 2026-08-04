"""Narrow application ports for external dependencies."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from incident_memory.models import IncidentEvidence, StoredIncident


class BedrockGateway(Protocol):
    """Embedding and generation capabilities required from Amazon Bedrock."""

    def generate_embedding(self, text: str) -> Sequence[float]:
        """Return the vector embedding for text."""

    def generate_recommendation(
        self,
        *,
        symptoms: str,
        evidence: Sequence[IncidentEvidence],
    ) -> str:
        """Generate a recommendation grounded only in the supplied evidence."""


class IncidentRepository(Protocol):
    """Constrained persistence operations needed by the application."""

    def save(self, incident: StoredIncident) -> None:
        """Persist one incident memory."""

    def find_similar(
        self,
        *,
        scope: str,
        embedding: Sequence[float],
        limit: int,
        service: str | None,
        environment: str | None,
    ) -> Sequence[IncidentEvidence]:
        """Return similar incidents within the required scope."""
