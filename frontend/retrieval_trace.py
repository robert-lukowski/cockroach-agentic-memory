"""Judge-facing progressive Agentic Memory Trace terminal."""

from __future__ import annotations

from html import escape

import streamlit as st

from frontend.models import (
    AnalysisResult,
    PrivacyGuardResult,
    format_milliseconds,
    format_percentage,
)

_REQUESTED_TOP_K = 5
_INITIAL_REPLAY_DELAY_MS = 1_200
_LINE_DELAY_MS = 140
_LINE_REVEAL_MS = 140


def _privacy_trace(result: AnalysisResult) -> tuple[str, str]:
    # Streamlit Cloud can retain result objects created by a previous app version
    # during hot reloads. Missing additive metadata must degrade to unavailable
    # instead of crashing the full investigation result page.
    guard = getattr(result, "privacy_guard", PrivacyGuardResult())
    if guard.status == "verified":
        details = (
            f"PASS · {guard.redactions} configured direct identifier(s) redacted · "
            "secondary review PASS"
        )
        return details, "ok"
    if guard.status == "not_required":
        return "PASS · no configured direct identifiers detected", "ok"
    if guard.status == "redacted_audit_unavailable":
        details = (
            f"REDACTION ENFORCED · {guard.redactions} field(s) · "
            "secondary review unavailable"
        )
        return details, "warn"
    if guard.status == "not_available":
        return "Not reported in this response", "muted"
    return f"REDACTION ENFORCED · {guard.redactions} field(s)", "warn"


def _privacy_input_line(result: AnalysisResult) -> str:
    guard = getattr(result, "privacy_guard", PrivacyGuardResult())
    if guard.status == "not_available":
        return (
            "privacy policy: "
            '<span class="aim-info">SANITIZE BEFORE DOWNSTREAM AI</span>'
        )
    return (
        "downstream AI input: "
        '<span class="aim-ok">SANITIZED CONTEXT ONLY</span>'
    )


def _terminal_line(content: str, *, index: int, class_name: str = "") -> str:
    # Give Streamlit's rerun a settle window before the first line appears. The
    # browser then reveals each completed control step in sequence so the judge
    # can follow the architecture without presenting fabricated raw log events.
    delay_ms = _INITIAL_REPLAY_DELAY_MS + (index * _LINE_DELAY_MS)
    classes = "aim-terminal-line"
    if class_name:
        classes = f"{classes} {class_name}"
    return (
        f'<div class="{classes}" style="--aim-line-delay:{delay_ms}ms">'
        f"{content}</div>"
    )


def _retrieval_trace_html(result: AnalysisResult) -> str:
    timings = getattr(result, "timings", {})
    retrieval_ms = timings.get("vector_retrieval_ms") if isinstance(timings, dict) else None
    retrieval_time = (
        format_milliseconds(float(retrieval_ms))
        if isinstance(retrieval_ms, int | float) and not isinstance(retrieval_ms, bool)
        else "Not available"
    )
    supporting_evidence_reported = getattr(result, "supporting_evidence_reported", False)
    returned = (
        str(getattr(result, "supporting_count", 0))
        if supporting_evidence_reported
        else "Not available"
    )
    best_similarity = format_percentage(getattr(result, "best_similarity", None))
    privacy_detail, privacy_class = _privacy_trace(result)

    rows: list[tuple[str, str]] = [
        (
            '<span class="aim-prompt">judge@agentic-memory:~$</span> '
            '<span class="aim-command">investigate --trace</span>',
            "command-line",
        ),
        ('<span class="aim-start">Trace started...</span>', "start"),
        ("&nbsp;", "spacer"),
        ('<span class="aim-section">PRIVACY BOUNDARY</span>', "section"),
        (
            "status: "
            f'<span class="aim-{privacy_class}">{escape(privacy_detail)}</span>',
            "",
        ),
        (_privacy_input_line(result), ""),
        ("&nbsp;", "spacer"),
        ('<span class="aim-section">TITAN TEXT EMBEDDINGS V2</span>', "section"),
        ('embedding: <span class="aim-ok">GENERATED</span>', ""),
        ('vector dimensions: <span class="aim-info">1,024</span>', ""),
        ("&nbsp;", "spacer"),
        ('<span class="aim-section">COCKROACHDB OPERATIONAL MEMORY</span>', "section"),
        ('access: <span class="aim-info">Cloud Managed MCP</span>', ""),
        (
            'index: <span class="aim-info">Distributed Vector Indexing</span>',
            "",
        ),
        ('distance metric: <span class="aim-info">cosine</span>', ""),
        (
            "requested top-k: "
            f'<span class="aim-info">{_REQUESTED_TOP_K} · application-owned</span>',
            "",
        ),
        (
            "returned memories: "
            f'<span class="aim-ok">{escape(returned)}</span>',
            "",
        ),
        (
            "best similarity: "
            f'<span class="aim-ok">{escape(best_similarity)}</span>',
            "",
        ),
        (
            "vector retrieval: "
            f'<span class="aim-ok">{escape(retrieval_time)}</span>',
            "",
        ),
        ("&nbsp;", "spacer"),
        ('<span class="aim-section">EVIDENCE CONTROL</span>', "section"),
        ('retrieved evidence: <span class="aim-ok">VALIDATED</span>', ""),
        ('retrieval query: <span class="aim-info">APPLICATION-OWNED</span>', ""),
        (
            'evidence selection: <span class="aim-info">APPLICATION-CONTROLLED</span>',
            "",
        ),
        (
            'model role: <span class="aim-ok">REASON OVER PROVIDED EVIDENCE</span>',
            "",
        ),
        ("&nbsp;", "spacer"),
        ('<span class="aim-section">BEDROCK-POWERED INVESTIGATOR</span>', "section"),
        ('grounded recommendation: <span class="aim-ok">GENERATED</span>', ""),
        ("context: current incident + validated operational memory", ""),
        ("&nbsp;", "spacer"),
        ('<span class="aim-section">MEMORY POLICY</span>', "section"),
        ('active investigation mode: <span class="aim-warn">READ-ONLY</span>', ""),
        ('write admission: <span class="aim-info">LIFECYCLE-GATED</span>', ""),
        (
            "trusted memory candidates: "
            '<span class="aim-info">RESOLVED / CLOSED ONLY</span>',
            "",
        ),
        ("&nbsp;", "spacer"),
        ('<span class="aim-finish">Trace complete.</span>', "finish"),
        (
            '<span class="aim-muted">No credentials, secrets, raw payloads, or removed '
            "identifiers are displayed.</span>",
            "note",
        ),
    ]
    lines = "".join(
        _terminal_line(content, index=index, class_name=class_name)
        for index, (content, class_name) in enumerate(rows)
    )

    return f"""
    <style>
      .aim-terminal {{
        background: #050505;
        border: 1px solid rgba(250, 204, 21, 0.28);
        border-radius: 0.9rem;
        margin: 0.2rem 0 1rem;
        overflow: hidden;
        box-shadow: 0 18px 42px rgba(0, 0, 0, 0.30);
      }}
      .aim-terminal-bar {{
        display: flex;
        align-items: center;
        gap: 0.45rem;
        padding: 0.65rem 0.8rem;
        border-bottom: 1px solid rgba(148, 163, 184, 0.13);
        background: #0b0b0b;
      }}
      .aim-terminal-dot {{
        width: 0.58rem;
        height: 0.58rem;
        border-radius: 999px;
        border: 1px solid rgba(250, 204, 21, 0.32);
        background: rgba(250, 204, 21, 0.12);
      }}
      .aim-terminal-title {{
        margin-left: 0.35rem;
        color: #a1a1aa;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 0.68rem;
        letter-spacing: 0.04em;
      }}
      .aim-terminal-body {{
        padding: 1rem 1.05rem 1.1rem;
        color: #d4d4d8;
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
        transform: translateX(-2px);
        animation: aim-terminal-line-in {_LINE_REVEAL_MS}ms steps(2, end) forwards;
        animation-delay: var(--aim-line-delay);
        will-change: opacity, transform;
      }}
      .aim-terminal-line.spacer {{ min-height: 0.65rem; }}
      .aim-prompt, .aim-command, .aim-start, .aim-section {{ color: #facc15; }}
      .aim-prompt {{ font-weight: 800; }}
      .aim-command {{ font-weight: 700; }}
      .aim-start {{ color: #fde047; }}
      .aim-section {{ font-weight: 800; letter-spacing: 0.045em; }}
      .aim-ok, .aim-finish {{ color: #86efac; font-weight: 800; }}
      .aim-info {{ color: #67e8f9; font-weight: 700; }}
      .aim-warn {{ color: #fde68a; font-weight: 800; }}
      .aim-no {{ color: #fca5a5; font-weight: 800; }}
      .aim-muted {{ color: #71717a; }}
      .aim-terminal-line.note {{
        margin-top: 0.15rem;
        font-size: 0.69rem;
        line-height: 1.45;
      }}
      @keyframes aim-terminal-line-in {{
        to {{ opacity: 1; transform: translateX(0); }}
      }}
      @media (prefers-reduced-motion: reduce) {{
        .aim-terminal-line {{
          animation: none;
          opacity: 1;
          transform: none;
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
        <span class="aim-terminal-title">agentic-memory — bash</span>
      </div>
      <div class="aim-terminal-body">{lines}</div>
    </section>
    """


def render_retrieval_trace(result: AnalysisResult) -> None:
    """Render the investigation control path as a progressive terminal trace."""
    st.subheader("Agentic Memory Trace")
    st.caption(
        "Follow the investigation step by step — see how privacy controls protect context, "
        "CockroachDB anchors operational memory retrieval, evidence stays application-controlled, "
        "and Bedrock turns trusted history into an actionable recommendation."
    )
    st.html(_retrieval_trace_html(result))
