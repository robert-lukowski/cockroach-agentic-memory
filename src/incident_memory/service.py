"""Deterministic RAG-style application orchestration."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from incident_memory.errors import AdapterContractError
from incident_memory.models import (
    EMBEDDING_DIMENSIONS,
    IncidentCreateRequest,
    IncidentCreateResponse,
    IncidentEvidence,
    InvestigationRequest,
    InvestigationResponse,
    StoredIncident,
)
from incident_memory.ports import BedrockGateway, IncidentRepository


class IncidentMemoryService:
    """Coordinates validation models, embeddings, retrieval, and generation."""

    def __init__(
        self,
        *,
        bedrock: BedrockGateway,
        repository: IncidentRepository,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._bedrock = bedrock
        self._repository = repository
        self._id_factory = id_factory
        self._clock = clock

    def create_incident(self, request: IncidentCreateRequest) -> IncidentCreateResponse:
        embedding = self._validated_embedding(
            self._bedrock.generate_embedding(request.embedding_text())
        )
        incident = StoredIncident(
            incident_id=self._id_factory(),
            scope=request.scope,
            service=request.service,
            environment=request.environment,
            title=request.title,
            symptoms=request.symptoms,
            root_cause=request.root_cause,
            resolution=request.resolution,
            tags=request.tags,
            metadata=request.metadata,
            embedding=embedding,
            created_at=self._clock(),
        )
        self._repository.save(incident)
        return IncidentCreateResponse(
            incident_id=incident.incident_id,
            created_at=incident.created_at,
        )

    def investigate(self, request: InvestigationRequest) -> InvestigationResponse:
        embedding = self._validated_embedding(
            self._bedrock.generate_embedding(request.symptoms)
        )
        results = tuple(
            self._repository.find_similar(
                scope=request.scope,
                embedding=embedding,
                limit=request.top_k,
                service=request.service,
                environment=request.environment,
            )
        )
        evidence = self._validated_evidence(results, request=request)
        recommendation = self._bedrock.generate_recommendation(
            symptoms=request.symptoms,
            evidence=evidence,
        ).strip()
        if not recommendation:
            raise AdapterContractError("The Bedrock adapter returned an empty recommendation.")
        return InvestigationResponse(recommendation=recommendation, evidence=evidence)

    @staticmethod
    def _validated_embedding(values: Sequence[float]) -> tuple[float, ...]:
        if len(values) != EMBEDDING_DIMENSIONS:
            raise AdapterContractError(
                f"The embedding adapter must return exactly {EMBEDDING_DIMENSIONS} values."
            )
        normalized: list[float] = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise AdapterContractError("The embedding adapter returned a non-numeric value.")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise AdapterContractError("The embedding adapter returned a non-finite value.")
            normalized.append(numeric)
        return tuple(normalized)

    @staticmethod
    def _validated_evidence(
        results: tuple[IncidentEvidence, ...],
        *,
        request: InvestigationRequest,
    ) -> tuple[IncidentEvidence, ...]:
        if len(results) > request.top_k:
            raise AdapterContractError("The repository returned more evidence than requested.")
        for item in results:
            if item.incident.scope != request.scope:
                raise AdapterContractError("The repository returned evidence from another scope.")
            if not math.isfinite(item.similarity):
                raise AdapterContractError("The repository returned an invalid similarity score.")
        return results
