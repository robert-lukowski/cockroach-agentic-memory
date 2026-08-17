"""Regression tests for the judge-facing Agentic Memory Trace."""

from __future__ import annotations

from typing import cast

from frontend.models import AnalysisResult, SupportingIncident
from frontend.retrieval_trace import _retrieval_trace_html


class _LegacyAnalysisResult:
    """Approximate an in-flight Streamlit result created before additive fields existed."""

    timings = {"vector_retrieval_ms": 12.5}
    supporting_count = 3
    best_similarity = 0.87
    recommendation = "Use validated evidence."


def test_retrieval_trace_tolerates_legacy_result_without_additive_metadata() -> None:
    legacy_result = cast(AnalysisResult, _LegacyAnalysisResult())

    html = _retrieval_trace_html(legacy_result)

    assert 'returned memories: <span class="aim-ok">Not available</span>' in html
    assert 'best similarity: <span class="aim-ok">87.0%</span>' in html
    assert "Operational-memory retrieval completed." in html
    assert "Investigation path complete." in html


def test_retrieval_trace_replays_at_deliberate_judge_pacing() -> None:
    legacy_result = cast(AnalysisResult, _LegacyAnalysisResult())

    html = _retrieval_trace_html(legacy_result)

    assert "--aim-line-delay:1200ms" in html
    assert "--aim-line-delay:1340ms" in html
    assert "140ms steps(1, end) forwards" in html
    assert "visibility: hidden" in html
    assert "prefers-reduced-motion: reduce" in html
    assert "<script" not in html.lower()


def test_retrieval_trace_uses_blue_control_center_terminal_theme() -> None:
    legacy_result = cast(AnalysisResult, _LegacyAnalysisResult())

    html = _retrieval_trace_html(legacy_result)

    assert "background: #012456" in html
    assert "border: 1px solid rgba(255, 255, 255, 0.38)" in html
    assert "agentic-memory — PowerShell" in html
    assert "PS Agentic-Memory&gt;" in html
    assert "#facc15" not in html
    assert "#050505" not in html


def test_retrieval_trace_centers_cockroachdb_and_governed_evidence() -> None:
    legacy_result = cast(AnalysisResult, _LegacyAnalysisResult())

    html = _retrieval_trace_html(legacy_result)

    assert "COCKROACHDB — TRUSTED OPERATIONAL MEMORY" in html
    assert "DURABLE OPERATIONAL MEMORY BACKBONE" in html
    assert "Distributed Vector Indexing" in html
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
    assert "PRIVACY BOUNDARY" not in html


def test_retrieval_trace_does_not_claim_history_when_no_memory_matches() -> None:
    result = AnalysisResult(
        recommendation="Use current incident evidence.",
        confidence=None,
        timings={"vector_retrieval_ms": 12.5},
        supporting_incidents=(),
        legacy_incident_ids=(),
        supporting_evidence_reported=True,
    )

    html = _retrieval_trace_html(result)

    assert 'returned memories: <span class="aim-ok">0</span>' in html
    assert "no matching trusted memory" in html
    assert "No matching trusted history found." in html
    assert "Trusted history retrieved." not in html


def test_retrieval_trace_keeps_matching_runtime_values_visible() -> None:
    result = AnalysisResult(
        recommendation="Use validated evidence.",
        confidence=None,
        timings={"vector_retrieval_ms": 12.5},
        supporting_incidents=(
            SupportingIncident(
                incident_id="incident-1",
                incident_number="INC0000001",
                service="synthetic-service",
                similarity=0.91,
                root_cause="Synthetic root cause",
                resolution="Synthetic resolution",
            ),
        ),
        legacy_incident_ids=(),
        supporting_evidence_reported=True,
    )

    html = _retrieval_trace_html(result)

    assert 'returned memories: <span class="aim-ok">1</span>' in html
    assert 'vector retrieval: <span class="aim-ok">12 ms</span>' in html
    assert "trusted operational memory" in html
    assert "Trusted history retrieved." in html


def test_retrieval_trace_uses_empty_space_for_real_result_summary() -> None:
    result = AnalysisResult(
        recommendation="Use validated evidence.",
        confidence=None,
        timings={},
        supporting_incidents=(
            SupportingIncident(
                incident_id="incident-1",
                incident_number="INC0000001",
                service="synthetic-service",
                similarity=0.91,
                root_cause="Synthetic root cause",
                resolution="Synthetic resolution",
            ),
        ),
        legacy_incident_ids=(),
        supporting_evidence_reported=True,
    )

    html = _retrieval_trace_html(result)

    assert "LIVE RESULT SUMMARY" in html
    assert "PLATFORM ADVANTAGE" in html
    assert "Recommendation" in html
    assert "GENERATED" in html
    assert "Trusted memories" in html
    assert "Best match" in html
    assert "91.0%" in html
    assert "AMAZON BEDROCK" in html
    assert "TITAN V2 · 1,024-D" in html
    assert "COCKROACHDB" in html
    assert "APPLICATION-CONTROLLED" in html
    assert "grid-template-columns: minmax(0, 1.55fr) minmax(17rem, 0.75fr)" in html
    assert "@media (max-width: 900px)" in html


def test_retrieval_trace_summary_does_not_invent_performance_claims() -> None:
    legacy_result = cast(AnalysisResult, _LegacyAnalysisResult())

    html = _retrieval_trace_html(legacy_result)

    assert "99.9%" not in html
    assert "SLA" not in html
    assert "faster" not in html.lower()
    assert "cost savings" not in html.lower()
