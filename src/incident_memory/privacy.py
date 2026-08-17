"""Privacy pre-hook that redacts direct identifiers before AI or vector processing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from incident_memory.errors import ApplicationError, PrivacyReviewRequiredError

_EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
    r"(?![A-Za-z0-9._%+-])"
)
_LABELED_PHONE_PATTERN = re.compile(
    r"(?im)^(\s*(?:phone|mobile|telephone|tel)\s*[:=]\s*)([^\r\n]{7,48})$"
)
_LABELED_NAME_PATTERN = re.compile(
    r"(?im)^(\s*(?:customer\s+name|contact\s+name|name)\s*[:=]\s*)([^\r\n]{2,96})$"
)
_STRICT_PHONE_VALUE_PATTERN = re.compile(r"^\+?[0-9][0-9().\s-]{5,30}[0-9]$")
_PHONE_FIELD_LABELS = {
    "phone",
    "phone number",
    "mobile",
    "mobile number",
    "telephone",
    "telephone number",
    "tel",
    "contact phone",
}
_NAME_FIELD_LABELS = {
    "name",
    "full name",
    "first name",
    "last name",
    "customer name",
    "contact name",
}


class PrivacyAuditGateway(Protocol):
    """Secondary AI reviewer that sees only already-redacted text."""

    def audit_privacy(self, *, text: str, categories: tuple[str, ...]) -> str:
        """Return PASS or REVIEW_REQUIRED for the sanitized payload."""


@dataclass(frozen=True, slots=True)
class PrivacyGuardReport:
    """Safe metadata describing redaction without exposing removed values."""

    status: str
    redactions: int
    categories: tuple[str, ...]
    ai_reviewed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "redactions": self.redactions,
            "categories": list(self.categories),
            "ai_reviewed": self.ai_reviewed,
        }


@dataclass(frozen=True, slots=True)
class ProtectedText:
    text: str
    report: PrivacyGuardReport


class PrivacyGuard:
    """Deterministic redaction with an optional Bedrock second-opinion audit."""

    def __init__(self, auditor: PrivacyAuditGateway | None = None) -> None:
        self._auditor = auditor

    @staticmethod
    def redact(text: str) -> ProtectedText:
        sanitized = text
        categories: list[str] = []
        redactions = 0

        sanitized, count = _EMAIL_PATTERN.subn("[REDACTED_EMAIL]", sanitized)
        if count:
            redactions += count
            categories.append("email")

        sanitized, count = _LABELED_PHONE_PATTERN.subn(
            lambda match: f"{match.group(1)}[REDACTED_PHONE]",
            sanitized,
        )
        if count:
            redactions += count
            categories.append("phone")

        sanitized, count = _LABELED_NAME_PATTERN.subn(
            lambda match: f"{match.group(1)}[REDACTED_NAME]",
            sanitized,
        )
        if count:
            redactions += count
            categories.append("name")

        unique_categories = tuple(dict.fromkeys(categories))
        return ProtectedText(
            text=sanitized,
            report=PrivacyGuardReport(
                status="redacted" if redactions else "not_required",
                redactions=redactions,
                categories=unique_categories,
                ai_reviewed=False,
            ),
        )

    @classmethod
    def redact_field(cls, text: str, *, label: str | None = None) -> ProtectedText:
        """Redact a bounded standalone field while using safe structural context when present."""
        protected = cls.redact(text)
        if protected.report.redactions:
            return protected

        normalized_label = ""
        if label:
            normalized_label = re.sub(r"[\s_-]+", " ", label.strip().lower())

        category: str | None = None
        replacement: str | None = None
        if normalized_label in _PHONE_FIELD_LABELS:
            category = "phone"
            replacement = "[REDACTED_PHONE]"
        elif normalized_label in _NAME_FIELD_LABELS:
            category = "name"
            replacement = "[REDACTED_NAME]"
        elif _STRICT_PHONE_VALUE_PATTERN.fullmatch(text.strip()):
            category = "phone"
            replacement = "[REDACTED_PHONE]"

        if category is None or replacement is None:
            return protected
        return ProtectedText(
            text=replacement,
            report=PrivacyGuardReport(
                status="redacted",
                redactions=1,
                categories=(category,),
                ai_reviewed=False,
            ),
        )

    def protect_for_investigation(self, text: str) -> ProtectedText:
        """Redact first, then let the secondary AI inspect only sanitized content."""
        protected = self.redact(text)
        if protected.report.redactions == 0 or self._auditor is None:
            return protected

        try:
            verdict = self._auditor.audit_privacy(
                text=protected.text,
                categories=protected.report.categories,
            )
        except ApplicationError:
            return ProtectedText(
                text=protected.text,
                report=PrivacyGuardReport(
                    status="redacted_audit_unavailable",
                    redactions=protected.report.redactions,
                    categories=protected.report.categories,
                    ai_reviewed=False,
                ),
            )

        if verdict == "REVIEW_REQUIRED":
            raise PrivacyReviewRequiredError(
                redactions=protected.report.redactions,
                categories=protected.report.categories,
            )
        if verdict != "PASS":
            return ProtectedText(
                text=protected.text,
                report=PrivacyGuardReport(
                    status="redacted_audit_unavailable",
                    redactions=protected.report.redactions,
                    categories=protected.report.categories,
                    ai_reviewed=False,
                ),
            )
        return ProtectedText(
            text=protected.text,
            report=PrivacyGuardReport(
                status="verified",
                redactions=protected.report.redactions,
                categories=protected.report.categories,
                ai_reviewed=True,
            ),
        )
