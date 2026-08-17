"""Deterministic RAG-style application orchestration."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

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
from incident_memory.privacy import PrivacyAuditGateway, PrivacyGuard

_SOURCE_ID_NAMESPACE = UUID("92ef77d7-0c4b-4ff9-b04e-8258902e7b41")


class IncidentMemoryService:
    """Coordinates privacy protection, embeddings, retrieval, and grounded generation."""

    def __init__(
        self,
        *,
        bedrock: BedrockGateway,
        repository: IncidentRepository,
        privacy_auditor: PrivacyAuditGateway | None = None,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        timer: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._bedrock = bedrock
        self._repository = repository
        self._privacy_guard = PrivacyGuard(privacy_auditor)
        self._id_factory = id_factory
        self._clock = clock
        self._timer = timer

    def create_incident(self, request: IncidentCreateRequest) -> IncidentCreateResponse:
        request = self._redacted_create_request(request)
        incident_id = (
            uuid5(_SOURCE_ID_NAMESPACE, request.source_id)
            if request.source_id is not None
            else self._id_factory()
        )
        existing = (
            self._repository.find_by_id(incident_id)
            if request.source_id is not None
            else None
        )
        if request.verify_only:
            status = (
                "absent"
                if existing is None
                else "already_present"
                if self._matches(existing, request)
                else "different"
            )
            return IncidentCreateResponse(
                incident_id=incident_id,
                created_at=existing.created_at if existing is not None else None,
                status=status,
            )
        if existing is not None and self._matches(existing, request):
            return IncidentCreateResponse(
                incident_id=incident_id,
                created_at=existing.created_at,
                status="already_present",
            )
        embedding = self._validated_embedding(
            self._bedrock.generate_embedding(request.embedding_text())
        )
        incident = StoredIncident(
            incident_id=incident_id,
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
            created_at=existing.created_at if existing is not None else self._clock(),
        )
        self._repository.save(incident)
        return IncidentCreateResponse(
            incident_id=incident.incident_id,
            created_at=incident.created_at,
            status="updated" if existing is not None else "created",
        )

    def _redacted_create_request(self, request: IncidentCreateRequest) -> IncidentCreateRequest:
        """Prevent direct identifiers from becoming durable memory or embedding input."""
        return replace(
            request,
            title=self._privacy_guard.redact(request.title).text,
            symptoms=self._privacy_guard.redact(request.symptoms).text,
            root_cause=self._privacy_guard.redact(request.root_cause).text,
            resolution=self._privacy_guard.redact(request.resolution).text,
        )

    @staticmethod
    def _matches(existing: StoredIncident, request: IncidentCreateRequest) -> bool:
        return (
            existing.scope == request.scope
            and existing.service == request.service
            and existing.environment == request.environment
            and existing.title == request.title
            and existing.symptoms == request.symptoms
            and existing.root_cause == request.root_cause
            and existing.resolution == request.resolution
            and existing.tags == request.tags
            and existing.metadata == request.metadata
        )

    def investigate(self, request: InvestigationRequest) -> InvestigationResponse:
        total_started = self._timer()

        privacy_started = self._timer()
        protected = self._privacy_guard.protect_for_investigation(request.symptoms)
        privacy_guard_ms = (self._timer() - privacy_started) * 1_000
        protected_request = replace(request, symptoms=protected.text)

        embedding = self._validated_embedding(
            self._bedrock.generate_embedding(protected_request.symptoms)
        )

        retrieval_started = self._timer()
        results = tuple(
            self._repository.find_similar(
                scope=protected_request.scope,
                embedding=embedding,
                limit=protected_request.top_k,
                service=protected_request.service,
                environment=protected_request.environment,
            )
        )
        vector_retrieval_ms = (self._timer() - retrieval_started) * 1_000
        evidence = self._validated_evidence(results, request=protected_request)
        evidence = self._redacted_evidence(evidence)

        generation_started = self._timer()
        recommendation = self._bedrock.generate_recommendation(
            symptoms=protected_request.symptoms,
            evidence=evidence,
        ).strip()
        bedrock_inference_ms = (self._timer() - generation_started) * 1_000
        if not recommendation:
            raise AdapterContractError("The Bedrock adapter returned an empty recommendation.")

        total_request_ms = (self._timer() - total_started) * 1_000
        return InvestigationResponse(
            recommendation=recommendation,
            evidence=evidence,
            privacy_guard=protected.report,
            timings={
                "privacy_guard_ms": privacy_guard_ms,
                "vector_retrieval_ms": vector_retrieval_ms,
                "bedrock_inference_ms": bedrock_inference_ms,
                "total_request_ms": total_request_ms,
            },
        )

    def _redacted_evidence(
        self,
        evidence: tuple[IncidentEvidence, ...],
    ) -> tuple[IncidentEvidence, ...]:
        """Apply the same boundary to historical evidence before Bedrock or API projection."""
        protected: list[IncidentEvidence] = []
        for item in evidence:
            incident = item.incident
            protected.append(
                replace(
                    item,
                    incident=replace(
                        incident,
                        title=self._privacy_guard.redact(incident.title).text,
                        symptoms=self._privacy_guard.redact(incident.symptoms).text,
                        root_cause=self._privacy_guard.redact(incident.root_cause).text,
                        resolution=self._privacy_guard.redact(incident.resolution).text,
                    ),
                )
            )
        return tuple(protected)

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
