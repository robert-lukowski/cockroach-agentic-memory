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
    assert 'returned memories: <span class="aim-ok">Not available</span>' in html
    assert 'best similarity: <span class="aim-ok">87.0%</span>' in html
    assert "Trace complete." in html


def test_retrieval_trace_has_visible_post_rerun_replay_window() -> None:
    legacy_result = cast(AnalysisResult, _LegacyAnalysisResult())

    html = _retrieval_trace_html(legacy_result)

    assert "--aim-line-delay:900ms" in html
    assert "--aim-line-delay:970ms" in html
    assert "110ms steps(2, end) forwards" in html
    assert "prefers-reduced-motion: reduce" in html
    assert "<script" not in html.lower()


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
    assert 'returned memories: <span class="aim-ok">0</span>' in html
    assert 'vector retrieval: <span class="aim-ok">12 ms</span>' in html
