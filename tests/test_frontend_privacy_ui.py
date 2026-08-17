"""Tests for judge-facing Privacy Guard rendering."""

from types import SimpleNamespace

from frontend.models import AnalysisResult, PrivacyGuardResult
from frontend.privacy_ui import _privacy_guard_html


def _result(guard: PrivacyGuardResult) -> AnalysisResult:
    return AnalysisResult(
        recommendation="Inspect the validated evidence.",
        confidence=None,
        timings={},
        supporting_incidents=(),
        legacy_incident_ids=(),
        privacy_guard=guard,
    )


def test_verified_card_shows_redaction_metadata_without_sensitive_values() -> None:
    html = _privacy_guard_html(
        _result(
            PrivacyGuardResult(
                status="verified",
                redactions=3,
                categories=("email", "phone", "name"),
                ai_reviewed=True,
            )
        )
    )

    assert "Privacy Guard Agent" in html
    assert "AI AUDIT PASS" in html
    assert "3 sensitive field(s) intercepted" in html
    assert "EMAIL · PHONE · NAME" in html
    assert "Secondary AI review Yes" in html
    assert "alex.morgan@example.invalid" not in html
    assert "+1 202-555-0147" not in html
    assert "Alex Morgan" not in html


def test_missing_backend_metadata_does_not_render_a_fake_privacy_claim() -> None:
    assert _privacy_guard_html(_result(PrivacyGuardResult())) == ""


def test_legacy_analysis_object_during_hot_reload_does_not_crash() -> None:
    legacy_result = SimpleNamespace(
        recommendation="Legacy result",
        timings={"bedrock_inference_ms": 12.0},
    )

    assert _privacy_guard_html(legacy_result) == ""
