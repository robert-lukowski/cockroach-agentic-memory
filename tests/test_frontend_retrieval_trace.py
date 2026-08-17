"""Regression tests for the judge-facing Agentic Memory Trace."""

from __future__ import annotations

from typing import cast

from frontend.models import AnalysisResult, PrivacyGuardResult
from frontend.retrieval_trace import _retrieval_trace_html


class _LegacyAnalysisResult:
    """Approximate an in-flight Streamlit result created before additive fields existed."""

    timings = {"vector_retrieval_ms": 12.5}
    supporting_count = 3
    best_similarity = 0.87


def test_retrieval_trace_tolerates_legacy_result_without_additive_metadata() -> None:
    legacy_result = cast(AnalysisResult, _LegacyAnalysisResult())

    html = _retrieval_trace_html(legacy_result)

    assert "Not reported in this response" in html
    assert "privacy policy:" in html
    assert "SANITIZE BEFORE DOWNSTREAM AI" in html
    assert 'returned memories: <span class="aim-ok">Not available</span>' in html
    assert 'best similarity: <span class="aim-ok">87.0%</span>' in html
    assert "Trace complete." in html


def test_retrieval_trace_replays_at_deliberate_judge_pacing() -> None:
    legacy_result = cast(AnalysisResult, _LegacyAnalysisResult())

    html = _retrieval_trace_html(legacy_result)

    assert "--aim-line-delay:1200ms" in html
    assert "--aim-line-delay:1340ms" in html
    assert "140ms steps(2, end) forwards" in html
    assert "prefers-reduced-motion: reduce" in html
    assert "<script" not in html.lower()


def test_retrieval_trace_frames_evidence_and_memory_controls_positively() -> None:
    legacy_result = cast(AnalysisResult, _LegacyAnalysisResult())

    html = _retrieval_trace_html(legacy_result)

    assert "retrieved evidence:" in html
    assert "VALIDATED" in html
    assert "retrieval query:" in html
    assert "APPLICATION-OWNED" in html
    assert "evidence selection:" in html
    assert "APPLICATION-CONTROLLED" in html
    assert "model role:" in html
    assert "REASON OVER PROVIDED EVIDENCE" in html
    assert "write admission:" in html
    assert "LIFECYCLE-GATED" in html
    assert "trusted memory candidates:" in html
    assert "RESOLVED / CLOSED ONLY" in html
    assert "model-selected SQL" not in html
    assert "model-selected evidence IDs" not in html
    assert "DISABLED FOR ACTIVE INCIDENT" not in html


def test_retrieval_trace_keeps_fresh_privacy_metadata_visible() -> None:
    result = AnalysisResult(
        recommendation="Use validated evidence.",
        confidence=None,
        timings={"vector_retrieval_ms": 12.5},
        supporting_incidents=(),
        legacy_incident_ids=(),
        privacy_guard=PrivacyGuardResult(
            status="verified",
            redactions=3,
            categories=("name", "email", "phone"),
            ai_reviewed=True,
        ),
        supporting_evidence_reported=True,
    )

    html = _retrieval_trace_html(result)

    assert "PASS · 3 configured direct identifier(s) redacted · secondary review PASS" in html
    assert "downstream AI input:" in html
    assert "SANITIZED CONTEXT ONLY" in html
    assert 'returned memories: <span class="aim-ok">0</span>' in html
    assert 'vector retrieval: <span class="aim-ok">12 ms</span>' in html
