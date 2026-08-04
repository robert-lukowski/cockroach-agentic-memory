"""Shared deterministic domain fixtures."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from incident_memory.models import EMBEDDING_DIMENSIONS, IncidentEvidence, StoredIncident


@pytest.fixture
def stored_incident() -> StoredIncident:
    return StoredIncident(
        incident_id=UUID("11111111-1111-4111-8111-111111111111"),
        scope="hackathon-demo",
        service="payments-api",
        environment="production",
        title="Connection pool exhaustion",
        symptoms="Checkout latency rose while database waits spiked.",
        root_cause="Lambda concurrency exceeded the configured connection pool.",
        resolution="Bound concurrency and increased the pool with saturation alerts.",
        tags=("database", "latency"),
        metadata={"severity": "SEV-2"},
        embedding=(0.25,) * EMBEDDING_DIMENSIONS,
        created_at=datetime(2026, 8, 4, 10, 30, tzinfo=UTC),
    )


@pytest.fixture
def evidence(stored_incident: StoredIncident) -> IncidentEvidence:
    return IncidentEvidence(incident=stored_incident, similarity=0.93)
