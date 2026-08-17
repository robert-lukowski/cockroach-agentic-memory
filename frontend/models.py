"""Frontend input and response models with no Streamlit dependency."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

_INCIDENT_NUMBER = re.compile(r"INC[0-9]{7,37}")
_TIMING_ALIASES = {
    "privacy_guard_ms": ("privacy_guard_ms", "privacy_ms"),
    "vector_retrieval_ms": (
        "vector_retrieval_ms",
        "retrieval_ms",
        "vector_search_ms",
    ),
    "bedrock_inference_ms": (
        "bedrock_inference_ms",
        "generation_ms",
        "inference_ms",
    ),
    "total_request_ms": (
        "total_request_ms",
        "total_response_ms",
        "total_ms",
        "duration_ms",
    ),
}


class InputValidationError(ValueError):
    """Raised when the investigation form is not safe to submit."""


class ResponseValidationError(ValueError):
    """Raised when the backend response cannot be rendered safely."""


@dataclass(frozen=True, slots=True)
class DemoScenario:
    key: str
    label: str
    incident_number: str
    title: str
    symptoms: str
    service: str
    environment: str


DEMO_SCENARIOS = (
    DemoScenario(
        key="connect-outbound",
        label="Amazon Connect outbound call failure",
        incident_number="INC9000003",
        title="Amazon Connect outbound calls fail after Lambda deployment",
        symptoms=(
            "The contact flow starts and Lambda completes, but the outbound call is not "
            "established. Intermittent timeouts appear after the deployment and a manual retry "
            "sometimes succeeds."
        ),
        service="connect-outbound-orchestrator",
        environment="development",
    ),
    DemoScenario(
        key="privacy-guard",
        label="Privacy Guard — incident with synthetic personal data",
        incident_number="INC9000099",
        title="Customer notification requests time out after deployment",
        symptoms=(
            "A customer reports repeated notification timeouts after the latest deployment.\n"
            "Name: Alex Morgan\n"
            "Email: alex.morgan@example.invalid\n"
            "Phone: +1 202-555-0147\n"
            "The notification worker retries successfully after several minutes."
        ),
        service="notification-orchestrator",
        environment="development",
    ),
    DemoScenario(
        key="iam-secrets",
        label="IAM / Secrets Manager access failure",
        incident_number="INC9000018",
        title="Incident API cannot load its managed service credential",
        symptoms=(
            "A newly started function reports access denied while loading its managed credential. "
            "Warm invocations that already have cached configuration remain healthy."
        ),
        service="incident-memory-api",
        environment="development",
    ),
    DemoScenario(
        key="database-pool",
        label="Database connection pool saturation",
        incident_number="INC9000030",
        title="Workers wait for database connections during a traffic burst",
        symptoms=(
            "Concurrent workers spend most of their execution waiting for database connections. "
            "Request latency and function timeouts rise together during the burst."
        ),
        service="campaign-state-store",
        environment="development",
    ),
)


@dataclass(frozen=True, slots=True)
class InvestigationInput:
    title: str
    symptoms: str
    service: str = ""
    environment: str = ""
    incident_number: str = ""

    def to_api_payload(
        self,
        *,
        incident_sys_id: str | None = None,
        opened_at: datetime | None = None,
    ) -> dict[str, str]:
        title = self.title.strip()
        symptoms = self.symptoms.strip()
        service = self.service.strip()
        environment = self.environment.strip()
        number = self.incident_number.strip()
        if not title:
            raise InputValidationError("Incident title is required.")
        if not symptoms:
            raise InputValidationError("Symptoms are required.")
        if len(title) > 256:
            raise InputValidationError("Incident title must contain at most 256 characters.")
        if len(service) > 256:
            raise InputValidationError("Service must contain at most 256 characters.")
        if len(environment) > 64:
            raise InputValidationError("Environment must contain at most 64 characters.")
        if len(number) > 40:
            raise InputValidationError("Incident number must contain at most 40 characters.")

        description = symptoms
        if environment:
            description = f"{symptoms}\n\nEnvironment: {environment}"
        if len(description) > 8_000:
            raise InputValidationError("Symptoms and environment must fit within 8000 characters.")

        generated_id = incident_sys_id or uuid4().hex
        if re.fullmatch(r"[0-9a-fA-F]{32}", generated_id) is None:
            raise InputValidationError("The generated request identifier is invalid.")
        request_time = opened_at or datetime.now(UTC)
        safe_number = number or f"DEMO-{generated_id[:8].upper()}"
        return {
            "incident_sys_id": generated_id.lower(),
            "number": safe_number,
            "short_description": title,
            "description": description,
            "category": "",
            "subcategory": "",
            "priority": "",
            "impact": "",
            "urgency": "",
            "assignment_group": "",
            "cmdb_ci": service,
            "opened_at": request_time.strftime("%Y-%m-%d %H:%M:%S"),
        }


@dataclass(frozen=True, slots=True)
class SupportingIncident:
    incident_id: str
    incident_number: str
    service: str
    similarity: float | None
    root_cause: str
    resolution: str

    @property
    def display_identifier(self) -> str:
        if _INCIDENT_NUMBER.fullmatch(self.incident_number):
            return self.incident_number
        return self.incident_id or self.incident_number or "Unknown incident"


@dataclass(frozen=True, slots=True)
class PrivacyGuardResult:
    status: str = "not_available"
    redactions: int = 0
    categories: tuple[str, ...] = ()
    ai_reviewed: bool = False


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    recommendation: str
    confidence: float | None
    timings: dict[str, float]
    supporting_incidents: tuple[SupportingIncident, ...]
    legacy_incident_ids: tuple[str, ...]
    privacy_guard: PrivacyGuardResult = PrivacyGuardResult()

    @property
    def supporting_count(self) -> int:
        return len(self.supporting_incidents) or len(self.legacy_incident_ids)

    @property
    def best_similarity(self) -> float | None:
        values = [
            item.similarity
            for item in self.supporting_incidents
            if item.similarity is not None
        ]
        return max(values) if values else None


def _optional_number(value: object, *, minimum: float = 0.0, maximum: float | None = None):
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < minimum:
        return None
    if maximum is not None and numeric > maximum:
        return None
    return numeric


def _optional_text(value: object, *, fallback: str = "") -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _normalize_timings(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, float] = {}
    for canonical, aliases in _TIMING_ALIASES.items():
        for alias in aliases:
            numeric = _optional_number(value.get(alias))
            if numeric is not None:
                normalized[canonical] = numeric
                break
    return normalized


def _normalize_privacy_guard(value: object) -> PrivacyGuardResult:
    if not isinstance(value, dict):
        return PrivacyGuardResult()
    status = _optional_text(value.get("status"), fallback="not_available")
    redactions_value = value.get("redactions")
    redactions = (
        redactions_value
        if (
            isinstance(redactions_value, int)
            and not isinstance(redactions_value, bool)
            and redactions_value >= 0
        )
        else 0
    )
    categories_value = value.get("categories")
    categories = (
        tuple(
            item.strip()
            for item in categories_value
            if isinstance(item, str) and item.strip()
        )
        if isinstance(categories_value, list)
        else ()
    )
    ai_reviewed = value.get("ai_reviewed") is True
    return PrivacyGuardResult(
        status=status,
        redactions=redactions,
        categories=categories,
        ai_reviewed=ai_reviewed,
    )


def _normalize_supporting_incidents(value: object) -> tuple[SupportingIncident, ...]:
    if not isinstance(value, list):
        return ()
    incidents: list[SupportingIncident] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        incident_id = _optional_text(item.get("incident_id"))
        incident_number = _optional_text(item.get("incident_number"), fallback=incident_id)
        service = _optional_text(item.get("service"), fallback="unknown")
        incidents.append(
            SupportingIncident(
                incident_id=incident_id,
                incident_number=incident_number,
                service=service,
                similarity=_optional_number(item.get("similarity"), maximum=1.0),
                root_cause=_optional_text(item.get("root_cause")),
                resolution=_optional_text(item.get("resolution")),
            )
        )
    incidents.sort(
        key=lambda item: item.similarity if item.similarity is not None else -1.0,
        reverse=True,
    )
    return tuple(incidents)


def _normalize_legacy_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        item.strip() for item in value if isinstance(item, str) and item.strip()
    )


def normalize_analysis_response(payload: object) -> AnalysisResult:
    """Normalize rich and legacy response shapes without exposing unknown fields."""
    if not isinstance(payload, dict):
        raise ResponseValidationError("The backend returned an invalid response object.")
    recommendation = _optional_text(payload.get("recommendation"))
    if not recommendation:
        raise ResponseValidationError("The backend returned an empty recommendation.")
    rich = _normalize_supporting_incidents(payload.get("supporting_incidents"))
    legacy = _normalize_legacy_ids(payload.get("supporting_incident_ids"))
    return AnalysisResult(
        recommendation=recommendation,
        confidence=_optional_number(payload.get("confidence"), maximum=1.0),
        timings=_normalize_timings(payload.get("timings")),
        supporting_incidents=rich,
        legacy_incident_ids=legacy,
        privacy_guard=_normalize_privacy_guard(payload.get("privacy_guard")),
    )


def format_percentage(value: float | None) -> str:
    return "Not available" if value is None else f"{value:.1%}"


def format_milliseconds(value: float | None) -> str:
    return "Not available" if value is None else f"{value:,.0f} ms"
