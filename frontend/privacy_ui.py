"""Judge-facing Privacy Guard presentation without echoing removed values in results."""

from __future__ import annotations

from html import escape

import streamlit as st

from frontend.models import AnalysisResult, PrivacyGuardResult, format_milliseconds

_ARCHITECTURE_URL = "https://github.com/robert-lukowski/cockroach-agentic-memory#architecture"
_AUTOMATION_URL = (
    "https://github.com/robert-lukowski/cockroach-agentic-memory/"
    "actions/workflows/generate-demo-incident.yml"
)


def _privacy_guard_html(result: AnalysisResult) -> str:
    # Streamlit Cloud can keep an in-flight object created by the previous app version
    # during a hot reload. Treat missing additive metadata as unavailable instead of
    # crashing the entire result page.
    guard = getattr(result, "privacy_guard", PrivacyGuardResult())
    if guard.status == "not_available":
        return ""

    if guard.status == "not_required":
        headline = "No configured direct identifiers detected"
        badge = "NO REDACTION NEEDED"
        detail = (
            "The deterministic privacy pre-hook found no email, labeled phone number, or "
            "labeled human name in this request."
        )
    elif guard.status == "verified":
        headline = f"{guard.redactions} sensitive field(s) intercepted before AI processing"
        badge = "AI AUDIT PASS"
        detail = (
            "Deterministic redaction ran before embeddings and investigation. The secondary "
            "Bedrock Privacy Guard agent then reviewed only the sanitized payload."
        )
    elif guard.status == "redacted_audit_unavailable":
        headline = f"{guard.redactions} sensitive field(s) redacted"
        badge = "REDACTION ENFORCED"
        detail = (
            "Direct identifiers were removed before downstream AI processing. The optional "
            "secondary Bedrock audit was unavailable for this request."
        )
    else:
        headline = f"{guard.redactions} sensitive field(s) redacted"
        badge = "PRIVACY PRE-HOOK"
        detail = "Configured direct identifiers were removed before downstream processing."

    categories = " · ".join(category.upper() for category in guard.categories) or "NONE"
    reviewed = "Yes" if guard.ai_reviewed else "No"
    timings = getattr(result, "timings", {})
    guard_ms = timings.get("privacy_guard_ms") if isinstance(timings, dict) else None
    timing_pill = (
        f'<span class="aim-privacy-pill">Guard time {format_milliseconds(guard_ms)}</span>'
        if guard_ms is not None
        else ""
    )
    return f"""
    <style>
      .aim-privacy-card {{
        border: 1px solid rgba(34, 197, 94, 0.28);
        border-radius: 1rem;
        padding: 1rem 1.05rem;
        margin: 0.2rem 0 1rem;
        background:
          linear-gradient(145deg, rgba(6, 78, 59, 0.22), rgba(8, 17, 32, 0.88));
        box-shadow: 0 14px 36px rgba(0, 0, 0, 0.18);
      }}
      .aim-privacy-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.8rem;
      }}
      .aim-privacy-agent {{
        color: #86EFAC;
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: 0.11em;
        text-transform: uppercase;
      }}
      .aim-privacy-badge {{
        border: 1px solid rgba(34, 197, 94, 0.35);
        border-radius: 999px;
        padding: 0.28rem 0.55rem;
        color: #BBF7D0;
        background: rgba(22, 101, 52, 0.18);
        font-size: 0.68rem;
        font-weight: 760;
      }}
      .aim-privacy-title {{
        color: #F8FAFC;
        font-size: 1rem;
        font-weight: 760;
        margin-top: 0.7rem;
      }}
      .aim-privacy-detail {{
        color: #CBD5E1;
        font-size: 0.78rem;
        line-height: 1.5;
        margin-top: 0.35rem;
      }}
      .aim-privacy-meta {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.45rem;
        margin-top: 0.7rem;
      }}
      .aim-privacy-pill {{
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 999px;
        padding: 0.28rem 0.5rem;
        color: #CBD5E1;
        background: rgba(15, 23, 42, 0.55);
        font-size: 0.68rem;
      }}
    </style>
    <section class="aim-privacy-card" aria-label="Privacy Guard Agent result">
      <div class="aim-privacy-header">
        <span class="aim-privacy-agent">Privacy Guard Agent · Pre-AI hook</span>
        <span class="aim-privacy-badge">{escape(badge)}</span>
      </div>
      <div class="aim-privacy-title">{escape(headline)}</div>
      <div class="aim-privacy-detail">{escape(detail)}</div>
      <div class="aim-privacy-meta">
        <span class="aim-privacy-pill">Redactions {guard.redactions}</span>
        <span class="aim-privacy-pill">Types {escape(categories)}</span>
        <span class="aim-privacy-pill">Secondary AI review {reviewed}</span>
        {timing_pill}
        <span class="aim-privacy-pill">Removed values not echoed in results</span>
      </div>
    </section>
    """


def render_privacy_guard(result: AnalysisResult) -> None:
    html = _privacy_guard_html(result)
    if not html:
        return
    st.subheader("Privacy Guard")
    st.caption("Pre-AI privacy boundary for the completed investigation request.")
    st.html(html)


def render_investigation_explanation() -> None:
    """Explain the real stage order including the privacy boundary."""
    st.subheader("What just happened?")
    st.markdown(
        "**Current Incident** → **Privacy Guard** → **Titan Embedding** → "
        "**CockroachDB Retrieval** → **Validated Evidence** → **Bedrock Investigator**"
    )
    st.markdown(
        "1. The Privacy Guard pre-hook removed configured direct identifiers before AI or "
        "vector processing.\n"
        "2. If redaction was needed, the secondary Bedrock Privacy Guard agent reviewed only "
        "the sanitized payload.\n"
        "3. Titan embedded the sanitized symptoms and CockroachDB retrieved similar resolved "
        "operational memories.\n"
        "4. The application validated and sanitized the retrieved evidence.\n"
        "5. The Bedrock Investigator received only controlled current symptoms and validated "
        "historical evidence, then generated the recommendation."
    )
    st.caption(
        "The timing values shown in Execution Telemetry are live per-request measurements; "
        "this stage description is not a distributed trace."
    )
    st.caption(
        "Trust boundary: models do not choose SQL, memory scope, or returned incident IDs. "
        "The Privacy Guard agent cannot access CockroachDB and never receives removed values. "
        "Only resolved or closed incidents become operational memory."
    )
    architecture, automation = st.columns(2)
    architecture.link_button(
        "View Architecture on GitHub",
        _ARCHITECTURE_URL,
        use_container_width=True,
    )
    automation.link_button(
        "View Automation on GitHub",
        _AUTOMATION_URL,
        use_container_width=True,
    )
