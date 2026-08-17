"""Deterministic RAG-style application orchestration."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from incident_memory.errors import AdapterContractError, ValidationError
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
        self._reject_sensitive_control(request.scope, field="scope")
        if request.source_id is not None:
            self._reject_sensitive_control(request.source_id, field="source_id")
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
            service=self._privacy_guard.redact_field(request.service, label="service").text,
            environment=self._privacy_guard.redact_field(
                request.environment,
                label="environment",
            ).text,
            title=self._privacy_guard.redact_field(request.title, label="title").text,
            symptoms=self._privacy_guard.redact_field(request.symptoms, label="symptoms").text,
            root_cause=self._privacy_guard.redact_field(
                request.root_cause,
                label="root_cause",
            ).text,
            resolution=self._privacy_guard.redact_field(
                request.resolution,
                label="resolution",
            ).text,
            tags=tuple(self._privacy_guard.redact_field(tag).text for tag in request.tags),
            metadata=self._redacted_metadata(request.metadata),
        )

    def _redacted_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Recursively sanitize metadata values and reject sensitive metadata keys."""
        sanitized: dict[str, Any] = {}
        for key, value in metadata.items():
            key_result = self._privacy_guard.redact_field(key)
            if key_result.text != key:
                raise ValidationError(
                    "metadata keys must not contain direct identifiers.",
                    details={"field": "metadata"},
                )
            sanitized[key] = self._redacted_metadata_value(value, label=key)
        return sanitized

    def _redacted_metadata_value(self, value: Any, *, label: str | None = None) -> Any:
        if isinstance(value, str):
            return self._privacy_guard.redact_field(value, label=label).text
        if isinstance(value, list):
            return [self._redacted_metadata_value(item, label=label) for item in value]
        if isinstance(value, tuple):
            return tuple(self._redacted_metadata_value(item, label=label) for item in value)
        if isinstance(value, dict):
            nested: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    nested[key] = self._redacted_metadata_value(item)
                    continue
                key_result = self._privacy_guard.redact_field(key)
                if key_result.text != key:
                    raise ValidationError(
                        "metadata keys must not contain direct identifiers.",
                        details={"field": "metadata"},
                    )
                nested[key] = self._redacted_metadata_value(item, label=key)
            return nested
        return value

    def _reject_sensitive_control(self, value: str, *, field: str) -> None:
        """Reject identifiers in control-plane fields whose mutation would change semantics."""
        if self._privacy_guard.redact_field(value, label=field).text != value:
            raise ValidationError(
                f"{field} must not contain direct identifiers.",
                details={"field": field},
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
        self._reject_sensitive_control(request.scope, field="scope")

        privacy_started = self._timer()
        protected = self._privacy_guard.protect_for_investigation(request.symptoms)
        privacy_guard_ms = (self._timer() - privacy_started) * 1_000
        protected_request = replace(
            request,
            symptoms=protected.text,
            service=(
                self._privacy_guard.redact_field(request.service, label="service").text
                if request.service is not None
                else None
            ),
            environment=(
                self._privacy_guard.redact_field(
                    request.environment,
                    label="environment",
                ).text
                if request.environment is not None
                else None
            ),
        )

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
                        service=self._privacy_guard.redact_field(
                            incident.service,
                            label="service",
                        ).text,
                        environment=self._privacy_guard.redact_field(
                            incident.environment,
                            label="environment",
                        ).text,
                        title=self._privacy_guard.redact_field(
                            incident.title,
                            label="title",
                        ).text,
                        symptoms=self._privacy_guard.redact_field(
                            incident.symptoms,
                            label="symptoms",
                        ).text,
                        root_cause=self._privacy_guard.redact_field(
                            incident.root_cause,
                            label="root_cause",
                        ).text,
                        resolution=self._privacy_guard.redact_field(
                            incident.resolution,
                            label="resolution",
                        ).text,
                        tags=tuple(
                            self._privacy_guard.redact_field(tag).text
                            for tag in incident.tags
                        ),
                        metadata=self._redacted_metadata(incident.metadata),
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
