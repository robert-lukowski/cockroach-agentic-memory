"""Focused tests for the Privacy Guard pre-AI boundary."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from incident_memory.errors import PrivacyReviewRequiredError
from incident_memory.privacy import PrivacyGuard


@dataclass
class FakePrivacyAuditor:
    verdict: str = "PASS"
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    def audit_privacy(self, *, text: str, categories: tuple[str, ...]) -> str:
        self.calls.append((text, categories))
        return self.verdict


def test_redacts_email_labeled_phone_and_labeled_name_before_audit() -> None:
    auditor = FakePrivacyAuditor()
    guard = PrivacyGuard(auditor)
    raw = (
        "Notification retries are failing.\n"
        "Name: Alex Morgan\n"
        "Email: alex.morgan@example.invalid\n"
        "Phone: +1 202-555-0147\n"
        "Retry succeeds after several minutes."
    )

    protected = guard.protect_for_investigation(raw)

    assert protected.report.status == "verified"
    assert protected.report.redactions == 3
    assert protected.report.categories == ("email", "phone", "name")
    assert protected.report.ai_reviewed is True
    assert "Alex Morgan" not in protected.text
    assert "alex.morgan@example.invalid" not in protected.text
    assert "+1 202-555-0147" not in protected.text
    assert "[REDACTED_NAME]" in protected.text
    assert "[REDACTED_EMAIL]" in protected.text
    assert "[REDACTED_PHONE]" in protected.text

    audited_text, audited_categories = auditor.calls[0]
    assert audited_text == protected.text
    assert audited_categories == protected.report.categories
    assert "Alex Morgan" not in audited_text
    assert "alex.morgan@example.invalid" not in audited_text
    assert "+1 202-555-0147" not in audited_text


def test_clean_text_does_not_spend_a_secondary_ai_call() -> None:
    auditor = FakePrivacyAuditor()
    guard = PrivacyGuard(auditor)

    protected = guard.protect_for_investigation(
        "Lambda retries time out after the deployment and no direct user details are present."
    )

    assert protected.report.status == "not_required"
    assert protected.report.redactions == 0
    assert protected.report.ai_reviewed is False
    assert auditor.calls == []


def test_review_required_stops_the_request_before_downstream_ai() -> None:
    guard = PrivacyGuard(FakePrivacyAuditor(verdict="REVIEW_REQUIRED"))

    with pytest.raises(PrivacyReviewRequiredError) as captured:
        guard.protect_for_investigation("Email: alex.morgan@example.invalid")

    assert captured.value.code == "privacy_review_required"
    assert captured.value.details == {"redactions": 1, "categories": ["email"]}
    assert "alex.morgan@example.invalid" not in str(captured.value)
