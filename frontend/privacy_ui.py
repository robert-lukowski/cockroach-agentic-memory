"""Judge-facing Privacy Guard presentation with no sensitive-value rendering."""

from __future__ import annotations

from html import escape

import streamlit as st

from frontend.models import AnalysisResult


def _privacy_guard_html(result: AnalysisResult) -> str:
    guard = result.privacy_guard
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
    return f"""
    <style>
      .aim-privacy-card {{
        border: 1px solid rgba(34, 197, 94, 0.28);
        border-radius: 1rem;
        padding: 1rem 1.05rem;
        margin: 0.2rem 0 1rem;
        background: linear-gradient(145deg, rgba(6, 78, 59, 0.22), rgba(8, 17, 32, 0.88));
        box-shadow: 0 14px 36px rgba(0, 0, 0, 0.18);
      }}
      .aim-privacy-header {{
        display:flex; justify-content:space-between; align-items:center; gap:0.8rem;
      }}
      .aim-privacy-agent {{
        color:#86EFAC; font-size:0.72rem; font-weight:800; letter-spacing:0.11em;
        text-transform:uppercase;
      }}
      .aim-privacy-badge {{
        border:1px solid rgba(34,197,94,0.35); border-radius:999px; padding:0.28rem 0.55rem;
        color:#BBF7D0; background:rgba(22,101,52,0.18); font-size:0.68rem; font-weight:760;
      }}
      .aim-privacy-title {{ color:#F8FAFC; font-size:1rem; font-weight:760; margin-top:0.7rem; }}
      .aim-privacy-detail {{ color:#CBD5E1; font-size:0.78rem; line-height:1.5; margin-top:0.35rem; }}
      .aim-privacy-meta {{ display:flex; flex-wrap:wrap; gap:0.45rem; margin-top:0.7rem; }}
      .aim-privacy-pill {{
        border:1px solid rgba(148,163,184,0.18); border-radius:999px; padding:0.28rem 0.5rem;
        color:#CBD5E1; background:rgba(15,23,42,0.55); font-size:0.68rem;
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
        <span class="aim-privacy-pill">Raw values never rendered</span>
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
