"""Validated request, domain, and response models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self
from uuid import UUID

from incident_memory.errors import ValidationError

EMBEDDING_DIMENSIONS = 1024

_INCIDENT_REQUIRED_FIELDS = {
    "scope",
    "service",
    "environment",
    "title",
    "symptoms",
    "root_cause",
    "resolution",
}
_INCIDENT_OPTIONAL_FIELDS = {"tags", "metadata"}
_INVESTIGATION_REQUIRED_FIELDS = {"scope", "symptoms"}
_INVESTIGATION_OPTIONAL_FIELDS = {"service", "environment", "top_k"}


def _require_object(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")
    return payload


def _validate_fields(
    payload: dict[str, Any],
    *,
    required: set[str],
    optional: set[str],
) -> None:
    missing = sorted(required - payload.keys())
    unexpected = sorted(payload.keys() - required - optional)
    if missing:
        raise ValidationError("Required fields are missing.", details={"missing": missing})
    if unexpected:
        raise ValidationError(
            "Request contains unsupported fields.",
            details={"unexpected": unexpected},
        )


def _required_string(payload: dict[str, Any], field: str, *, maximum: int) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(
            f"{field} must be a non-empty string.",
            details={"field": field},
        )
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValidationError(
            f"{field} must contain at most {maximum} characters.",
            details={"field": field, "maximum": maximum},
        )
    return normalized


def _optional_string(payload: dict[str, Any], field: str, *, maximum: int) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(
            f"{field} must be a non-empty string when provided.",
            details={"field": field},
        )
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValidationError(
            f"{field} must contain at most {maximum} characters.",
            details={"field": field, "maximum": maximum},
        )
    return normalized


def _tags(payload: dict[str, Any]) -> tuple[str, ...]:
    value = payload.get("tags", [])
    if not isinstance(value, list) or len(value) > 20:
        raise ValidationError("tags must be an array containing at most 20 strings.")

    normalized: list[str] = []
    for tag in value:
        if not isinstance(tag, str) or not tag.strip() or len(tag.strip()) > 64:
            raise ValidationError("Each tag must be a non-empty string of at most 64 characters.")
        clean_tag = tag.strip()
        if clean_tag not in normalized:
            normalized.append(clean_tag)
    return tuple(normalized)


def _metadata(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("metadata", {})
    if not isinstance(value, dict):
        raise ValidationError("metadata must be a JSON object.")
    if len(json.dumps(value, separators=(",", ":"), ensure_ascii=False)) > 8_192:
        raise ValidationError("metadata must serialize to at most 8192 characters.")
    return dict(value)


@dataclass(frozen=True, slots=True)
class IncidentCreateRequest:
    """Validated payload used to create an incident memory."""

    scope: str
    service: str
    environment: str
    title: str
    symptoms: str
    root_cause: str
    resolution: str
    tags: tuple[str, ...]
    metadata: dict[str, Any]

    @classmethod
    def from_payload(cls, raw_payload: object) -> Self:
        payload = _require_object(raw_payload)
        _validate_fields(
            payload,
            required=_INCIDENT_REQUIRED_FIELDS,
            optional=_INCIDENT_OPTIONAL_FIELDS,
        )
        return cls(
            scope=_required_string(payload, "scope", maximum=64),
            service=_required_string(payload, "service", maximum=128),
            environment=_required_string(payload, "environment", maximum=64),
            title=_required_string(payload, "title", maximum=256),
            symptoms=_required_string(payload, "symptoms", maximum=8_000),
            root_cause=_required_string(payload, "root_cause", maximum=8_000),
            resolution=_required_string(payload, "resolution", maximum=8_000),
            tags=_tags(payload),
            metadata=_metadata(payload),
        )

    def embedding_text(self) -> str:
        """Build the stable text representation used for incident embeddings."""
        return "\n".join(
            (
                f"Service: {self.service}",
                f"Environment: {self.environment}",
                f"Title: {self.title}",
                f"Symptoms: {self.symptoms}",
                f"Root cause: {self.root_cause}",
                f"Resolution: {self.resolution}",
            )
        )


@dataclass(frozen=True, slots=True)
class InvestigationRequest:
    """Validated incident-investigation payload."""

    scope: str
    symptoms: str
    service: str | None
    environment: str | None
    top_k: int

    @classmethod
    def from_payload(cls, raw_payload: object) -> Self:
        payload = _require_object(raw_payload)
        _validate_fields(
            payload,
            required=_INVESTIGATION_REQUIRED_FIELDS,
            optional=_INVESTIGATION_OPTIONAL_FIELDS,
        )
        raw_top_k = payload.get("top_k", 5)
        if isinstance(raw_top_k, bool) or not isinstance(raw_top_k, int):
            raise ValidationError("top_k must be an integer between 1 and 10.")
        if not 1 <= raw_top_k <= 10:
            raise ValidationError("top_k must be between 1 and 10.")
        return cls(
            scope=_required_string(payload, "scope", maximum=64),
            symptoms=_required_string(payload, "symptoms", maximum=8_000),
            service=_optional_string(payload, "service", maximum=128),
            environment=_optional_string(payload, "environment", maximum=64),
            top_k=raw_top_k,
        )


@dataclass(frozen=True, slots=True)
class StoredIncident:
    """Incident memory persisted through the repository port."""

    incident_id: UUID
    scope: str
    service: str
    environment: str
    title: str
    symptoms: str
    root_cause: str
    resolution: str
    tags: tuple[str, ...]
    metadata: dict[str, Any]
    embedding: tuple[float, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class IncidentEvidence:
    """A stored incident returned by similarity search."""

    incident: StoredIncident
    similarity: float

    def generation_context(self) -> dict[str, Any]:
        return {
            "incident_id": str(self.incident.incident_id),
            "service": self.incident.service,
            "environment": self.incident.environment,
            "title": self.incident.title,
            "symptoms": self.incident.symptoms,
            "root_cause": self.incident.root_cause,
            "resolution": self.incident.resolution,
            "similarity": self.similarity,
        }


@dataclass(frozen=True, slots=True)
class IncidentCreateResponse:
    incident_id: UUID
    created_at: datetime

    def as_dict(self) -> dict[str, str]:
        return {
            "incident_id": str(self.incident_id),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class InvestigationResponse:
    recommendation: str
    evidence: tuple[IncidentEvidence, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "recommendation": self.recommendation,
            "supporting_incident_ids": [
                str(item.incident.incident_id) for item in self.evidence
            ],
            "evidence": [
                {
                    "incident_id": str(item.incident.incident_id),
                    "title": item.incident.title,
                    "similarity": item.similarity,
                }
                for item in self.evidence
            ],
        }
