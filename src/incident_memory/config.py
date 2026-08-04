"""Environment-backed, secret-safe application configuration."""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from incident_memory.models import EMBEDDING_DIMENSIONS


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str
    app_mode: str
    repository_backend: str
    embedding_model_id: str
    generation_model_id: str
    embedding_dimensions: int
    issues: tuple[str, ...] = ()

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> Self:
        values = os.environ if environment is None else environment
        issues: list[str] = []
        raw_dimensions = values.get("EMBEDDING_DIMENSIONS", str(EMBEDDING_DIMENSIONS))
        try:
            dimensions = int(raw_dimensions)
        except ValueError:
            dimensions = EMBEDDING_DIMENSIONS
            issues.append("EMBEDDING_DIMENSIONS must be an integer.")
        if dimensions != EMBEDDING_DIMENSIONS:
            issues.append(f"EMBEDDING_DIMENSIONS must be {EMBEDDING_DIMENSIONS} for this schema.")

        return cls(
            service_name=values.get("SERVICE_NAME", "agentic-incident-memory"),
            app_mode=values.get("APP_MODE", "scaffold"),
            repository_backend=values.get("REPOSITORY_BACKEND", "unconfigured"),
            embedding_model_id=values.get("BEDROCK_EMBEDDING_MODEL_ID", ""),
            generation_model_id=values.get("BEDROCK_GENERATION_MODEL_ID", ""),
            embedding_dimensions=dimensions,
            issues=tuple(issues),
        )

    def health_payload(self) -> dict[str, object]:
        """Return status booleans and non-sensitive process metadata only."""
        return {
            "status": "ok" if not self.issues else "degraded",
            "process": {
                "service": self.service_name,
                "python": platform.python_version(),
                "mode": self.app_mode,
            },
            "configuration": {
                "valid": not self.issues,
                "issues": list(self.issues),
                "embedding_dimensions": self.embedding_dimensions,
                "embedding_model_configured": bool(self.embedding_model_id),
                "generation_model_configured": bool(self.generation_model_id),
                "repository_configured": self.repository_backend not in {"", "unconfigured"},
                "live_adapters_enabled": False,
            },
        }
