"""Regression tests for the judge-facing Agentic Memory Trace."""

from __future__ import annotations

from typing import cast

from frontend.models import AnalysisResult
from frontend.retrieval_trace import _retrieval_trace_html


class _LegacyAnalysisResult:
    """Approximate an in-flight Streamlit result created before additive fields existed."""

    timings = {"vector_retrieval_ms": 12.5}
    supporting_count = 3
    best_similarity = 0.87


def test_retrieval_trace_tolerates_legacy_result_without_additive_metadata() -> None:
    legacy_result = cast(AnalysisResult, _LegacyAnalysisResult())

    html = _retrieval_trace_html(legacy_result)

    assert "Not available in this response" in html
    assert 'returned memories: <span class="aim-ok">Not available</span>' in html
    assert 'best similarity: <span class="aim-ok">87.0%</span>' in html
    assert "Trace complete." in html
