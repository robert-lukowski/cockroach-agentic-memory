"""Environment-backed, secret-safe application configuration."""

from __future__ import annotations

import os
import platform
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from incident_memory.models import EMBEDDING_DIMENSIONS

_SCOPE_PATTERN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{0,63}")


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str
    app_mode: str
    repository_backend: str
    embedding_model_id: str
    generation_model_id: str
    embedding_dimensions: int
    aws_region: str
    mcp_url: str
    mcp_secret_arn: str
    cockroach_cluster_id: str
    cockroach_database: str
    servicenow_memory_scope: str
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

        app_mode = values.get("APP_MODE", "scaffold")
        mcp_secret_arn = values.get("MCP_SECRET_ARN", "")
        cockroach_cluster_id = values.get("COCKROACH_CLUSTER_ID", "")
        generation_model_id = values.get("BEDROCK_GENERATION_MODEL_ID", "")
        embedding_model_id = values.get("BEDROCK_EMBEDDING_MODEL_ID", "")
        servicenow_memory_scope = values.get("SERVICENOW_MEMORY_SCOPE", "servicenow-dev")
        if _SCOPE_PATTERN.fullmatch(servicenow_memory_scope) is None:
            issues.append(
                "SERVICENOW_MEMORY_SCOPE must be 1-64 characters using letters, numbers, ._:-."
            )
        if app_mode == "live":
            required_values = {
                "MCP_SECRET_ARN": mcp_secret_arn,
                "COCKROACH_CLUSTER_ID": cockroach_cluster_id,
                "BEDROCK_EMBEDDING_MODEL_ID": embedding_model_id,
                "BEDROCK_GENERATION_MODEL_ID": generation_model_id,
            }
            for name, value in required_values.items():
                if not value:
                    issues.append(f"{name} is required in live mode.")

        return cls(
            service_name=values.get("SERVICE_NAME", "agentic-incident-memory"),
            app_mode=app_mode,
            repository_backend=values.get("REPOSITORY_BACKEND", "unconfigured"),
            embedding_model_id=embedding_model_id,
            generation_model_id=generation_model_id,
            embedding_dimensions=dimensions,
            aws_region=values.get("AWS_REGION", values.get("AWS_DEFAULT_REGION", "eu-central-1")),
            mcp_url=values.get("MCP_URL", "https://cockroachlabs.cloud/mcp"),
            mcp_secret_arn=mcp_secret_arn,
            cockroach_cluster_id=cockroach_cluster_id,
            cockroach_database=values.get("COCKROACH_DATABASE", "defaultdb"),
            servicenow_memory_scope=servicenow_memory_scope,
            issues=tuple(issues),
        )

    @property
    def live_adapters_enabled(self) -> bool:
        return self.app_mode == "live" and not self.issues

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
                "live_adapters_enabled": self.live_adapters_enabled,
            },
        }
