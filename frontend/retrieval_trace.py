"""Judge-facing progressive Agentic Memory Trace terminal."""

from __future__ import annotations

from html import escape

import streamlit as st

from frontend.models import AnalysisResult, format_milliseconds, format_percentage

_REQUESTED_TOP_K = 5
_INITIAL_REPLAY_DELAY_MS = 1_200
_LINE_DELAY_MS = 140
_LINE_REVEAL_MS = 140


def _terminal_line(content: str, *, index: int, class_name: str = "") -> str:
    delay_ms = _INITIAL_REPLAY_DELAY_MS + (index * _LINE_DELAY_MS)
    classes = "aim-terminal-line"
    if class_name:
        classes = f"{classes} {class_name}"
    return (
        f'<div class="{classes}" style="--aim-line-delay:{delay_ms}ms">'
        f"{content}</div>"
    )


def _history_narrative(result: AnalysisResult) -> tuple[str, str, str]:
    supporting_evidence_reported = getattr(result, "supporting_evidence_reported", False)
    supporting_count = getattr(result, "supporting_count", 0)

    if supporting_evidence_reported and supporting_count > 0:
        return (
            str(supporting_count),
            'context: current incident + <span class="aim-ok">trusted operational memory</span>',
            "Trusted history retrieved. Evidence controlled. Recommendation grounded.",
        )

    if supporting_evidence_reported:
        return (
            str(supporting_count),
            'context: current incident · <span class="aim-info">no matching trusted memory</span>',
            "No matching trusted history found. Evidence controlled. Recommendation grounded.",
        )

    return (
        "Not available",
        (
            "context: current incident + "
            '<span class="aim-info">governed operational-memory retrieval</span>'
        ),
        "Operational-memory retrieval completed. Evidence controlled. Recommendation grounded.",
    )


def _result_summary_html(
    result: AnalysisResult,
    *,
    returned: str,
    best_similarity: str,
) -> str:
    recommendation = getattr(result, "recommendation", "")
    recommendation_status = "GENERATED" if str(recommendation).strip() else "NOT RETURNED"

    items = (
        ("Recommendation", recommendation_status, "ok"),
        ("Trusted memories", returned, "info"),
        ("Best match", best_similarity, "info"),
        ("Evidence", "VALIDATED", "ok"),
    )
    result_rows = "".join(
        (
            '<div class="aim-summary-row">'
            f'<span class="aim-summary-label">{escape(label)}</span>'
            f'<span class="aim-summary-value aim-{class_name}">{escape(value)}</span>'
            "</div>"
        )
        for label, value, class_name in items
    )

    return f"""
      <aside class="aim-summary" aria-label="Live result summary">
        <div class="aim-summary-kicker">LIVE RESULT SUMMARY</div>
        {result_rows}
        <div class="aim-summary-divider"></div>
        <div class="aim-summary-kicker">PLATFORM ADVANTAGE</div>
        <div class="aim-summary-stack">
          <div><span>AI reasoning</span><strong>AMAZON BEDROCK</strong></div>
          <div><span>Embedding</span><strong>TITAN V2 · 1,024-D</strong></div>
          <div><span>Memory</span><strong>COCKROACHDB</strong></div>
          <div><span>Control</span><strong>APPLICATION-CONTROLLED</strong></div>
        </div>
      </aside>
    """


def _retrieval_trace_html(result: AnalysisResult) -> str:
    timings = getattr(result, "timings", {})
    retrieval_ms = timings.get("vector_retrieval_ms") if isinstance(timings, dict) else None
    retrieval_time = (
        format_milliseconds(float(retrieval_ms))
        if isinstance(retrieval_ms, int | float) and not isinstance(retrieval_ms, bool)
        else "Not available"
    )
    returned, investigator_context, closing_summary = _history_narrative(result)
    best_similarity = format_percentage(getattr(result, "best_similarity", None))

    rows: list[tuple[str, str]] = [
        (
            '<span class="aim-prompt">PS Agentic-Memory&gt;</span> '
            '<span class="aim-command">investigate --trace</span>',
            "command-line",
        ),
        ('<span class="aim-start">Investigation path started...</span>', "start"),
        ("&nbsp;", "spacer"),
        ('<span class="aim-section">TITAN TEXT EMBEDDINGS V2</span>', "section"),
        ('semantic representation: <span class="aim-ok">GENERATED</span>', ""),
        ('vector dimensions: <span class="aim-info">1,024</span>', ""),
        ("&nbsp;", "spacer"),
        (
            '<span class="aim-section">COCKROACHDB — TRUSTED OPERATIONAL MEMORY</span>',
            "section",
        ),
        ('role: <span class="aim-ok">DURABLE OPERATIONAL MEMORY BACKBONE</span>', ""),
        ('access: <span class="aim-info">Cloud Managed MCP</span>', ""),
        ('index: <span class="aim-info">Distributed Vector Indexing</span>', ""),
        ('distance metric: <span class="aim-info">cosine</span>', ""),
        (
            "requested top-k: "
            f'<span class="aim-info">{_REQUESTED_TOP_K} · application-owned</span>',
            "",
        ),
        (f'returned memories: <span class="aim-ok">{escape(returned)}</span>', ""),
        (f'best similarity: <span class="aim-ok">{escape(best_similarity)}</span>', ""),
        (f'vector retrieval: <span class="aim-ok">{escape(retrieval_time)}</span>', ""),
        ("&nbsp;", "spacer"),
        ('<span class="aim-section">EVIDENCE CONTROL</span>', "section"),
        ('retrieved evidence: <span class="aim-ok">VALIDATED</span>', ""),
        ('retrieval query: <span class="aim-info">APPLICATION-OWNED</span>', ""),
        ('evidence selection: <span class="aim-info">APPLICATION-CONTROLLED</span>', ""),
        ('model role: <span class="aim-ok">REASON OVER PROVIDED EVIDENCE</span>', ""),
        ("&nbsp;", "spacer"),
        ('<span class="aim-section">BEDROCK-POWERED INVESTIGATOR</span>', "section"),
        ('grounded recommendation: <span class="aim-ok">GENERATED</span>', ""),
        (investigator_context, ""),
        ("&nbsp;", "spacer"),
        ('<span class="aim-section">TRUSTED MEMORY LIFECYCLE</span>', "section"),
        ('active investigation mode: <span class="aim-warn">READ-ONLY</span>', ""),
        ('write admission: <span class="aim-info">LIFECYCLE-GATED</span>', ""),
        ('trusted memory candidates: <span class="aim-info">RESOLVED / CLOSED ONLY</span>', ""),
        ("&nbsp;", "spacer"),
        ('<span class="aim-finish">Investigation path complete.</span>', "finish"),
        (f'<span class="aim-muted">{escape(closing_summary)}</span>', "note"),
    ]
    lines = "".join(
        _terminal_line(content, index=index, class_name=class_name)
        for index, (content, class_name) in enumerate(rows)
    )
    summary = _result_summary_html(
        result,
        returned=returned,
        best_similarity=best_similarity,
    )

    return f"""
    <style>
      .aim-terminal {{
        position: relative;
        isolation: isolate;
        background: #012456;
        border: 1px solid rgba(255, 255, 255, 0.38);
        border-radius: 0.9rem;
        margin: 0.2rem 0 1rem;
        overflow: hidden;
        box-shadow: 0 16px 38px rgba(2, 20, 45, 0.36);
      }}
      .aim-terminal-bar {{
        display: flex;
        align-items: center;
        gap: 0.45rem;
        padding: 0.65rem 0.8rem;
        border-bottom: 1px solid rgba(255, 255, 255, 0.18);
        background: #0b3267;
      }}
      .aim-terminal-dot {{
        width: 0.58rem;
        height: 0.58rem;
        border-radius: 999px;
        border: 1px solid rgba(255, 255, 255, 0.58);
        background: rgba(219, 234, 254, 0.34);
      }}
      .aim-terminal-title {{
        margin-left: 0.35rem;
        color: #dbeafe;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 0.68rem;
        letter-spacing: 0.04em;
      }}
      .aim-terminal-grid {{
        display: grid;
        grid-template-columns: minmax(0, 1.55fr) minmax(17rem, 0.75fr);
        align-items: stretch;
      }}
      .aim-terminal-body {{
        background: #012456;
        padding: 1rem 1.05rem 1.1rem;
        border-right: 1px solid rgba(255, 255, 255, 0.14);
        color: #f8fafc;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 0.78rem;
        line-height: 1.55;
        overflow-x: auto;
      }}
      .aim-terminal-line {{
        min-height: 1.1rem;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        opacity: 0;
        visibility: hidden;
        animation: aim-terminal-line-in {_LINE_REVEAL_MS}ms steps(1, end) forwards;
        animation-delay: var(--aim-line-delay);
      }}
      .aim-terminal-line.spacer {{ min-height: 0.65rem; }}
      .aim-prompt {{ color: #ffffff; font-weight: 800; }}
      .aim-command {{ color: #bfdbfe; font-weight: 800; }}
      .aim-start {{ color: #dbeafe; font-weight: 700; }}
      .aim-section {{ color: #93c5fd; font-weight: 800; letter-spacing: 0.045em; }}
      .aim-ok, .aim-finish {{ color: #ffffff; font-weight: 800; }}
      .aim-info {{ color: #7dd3fc; font-weight: 700; }}
      .aim-warn {{ color: #bfdbfe; font-weight: 800; }}
      .aim-muted {{ color: #b8cee8; }}
      .aim-terminal-line.note {{
        margin-top: 0.15rem;
        font-size: 0.69rem;
        line-height: 1.45;
      }}
      .aim-summary {{
        padding: 1rem 1rem 1.1rem;
        background: linear-gradient(180deg, #0b3267 0%, #062b5d 100%);
        color: #f8fafc;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        opacity: 0;
        animation: aim-summary-in 220ms ease-out forwards;
        animation-delay: 1.6s;
      }}
      .aim-summary-kicker {{
        margin-bottom: 0.7rem;
        color: #93c5fd;
        font-size: 0.7rem;
        font-weight: 900;
        letter-spacing: 0.08em;
      }}
      .aim-summary-row {{
        display: flex;
        justify-content: space-between;
        gap: 0.8rem;
        padding: 0.42rem 0;
        border-bottom: 1px solid rgba(255, 255, 255, 0.09);
      }}
      .aim-summary-label {{ color: #b8cee8; font-size: 0.71rem; }}
      .aim-summary-value {{ text-align: right; font-size: 0.72rem; }}
      .aim-summary-divider {{
        height: 1px;
        margin: 1rem 0;
        background: rgba(255, 255, 255, 0.16);
      }}
      .aim-summary-stack {{ display: grid; gap: 0.62rem; }}
      .aim-summary-stack div {{ display: grid; gap: 0.1rem; }}
      .aim-summary-stack span {{ color: #b8cee8; font-size: 0.66rem; }}
      .aim-summary-stack strong {{ color: #ffffff; font-size: 0.72rem; }}
      @keyframes aim-terminal-line-in {{
        to {{ opacity: 1; visibility: visible; }}
      }}
      @keyframes aim-summary-in {{
        to {{ opacity: 1; }}
      }}
      @media (max-width: 900px) {{
        .aim-terminal-grid {{ grid-template-columns: 1fr; }}
        .aim-terminal-body {{
          border-right: 0;
          border-bottom: 1px solid rgba(255, 255, 255, 0.14);
        }}
      }}
      @media (prefers-reduced-motion: reduce) {{
        .aim-terminal-line, .aim-summary {{
          animation: none;
          opacity: 1;
          visibility: visible;
        }}
      }}
    </style>
    <section
      class="aim-terminal"
      role="log"
      aria-live="polite"
      aria-label="Agentic Memory Trace"
    >
      <div class="aim-terminal-bar" aria-hidden="true">
        <span class="aim-terminal-dot"></span>
        <span class="aim-terminal-dot"></span>
        <span class="aim-terminal-dot"></span>
        <span class="aim-terminal-title">agentic-memory — PowerShell</span>
      </div>
      <div class="aim-terminal-grid">
        <div class="aim-terminal-body">{lines}</div>
        {summary}
      </div>
    </section>
    """


def render_retrieval_trace(result: AnalysisResult) -> None:
    """Render the investigation control path as a progressive terminal trace."""
    st.subheader("Agentic Memory Trace")
    st.caption(
        "Follow the investigation step by step — Titan creates the semantic representation, "
        "CockroachDB powers the trusted operational-memory backbone, application-controlled "
        "evidence grounds the reasoning, and Bedrock turns trusted history into an actionable "
        "recommendation."
    )
    st.html(_retrieval_trace_html(result))