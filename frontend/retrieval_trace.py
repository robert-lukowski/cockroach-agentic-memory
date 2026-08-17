"""Judge-facing CockroachDB retrieval proof panel."""

from __future__ import annotations

import streamlit as st

from frontend.models import AnalysisResult, format_milliseconds

_REQUESTED_TOP_K = 5


def _retrieval_trace_html(result: AnalysisResult) -> str:
    retrieval_ms = result.timings.get("vector_retrieval_ms")
    retrieval_time = (
        format_milliseconds(float(retrieval_ms))
        if isinstance(retrieval_ms, int | float) and not isinstance(retrieval_ms, bool)
        else "Not available"
    )
    returned = result.supporting_count
    return f"""
    <style>
      .aim-retrieval-trace {{
        border: 1px solid rgba(105, 51, 255, 0.32);
        border-radius: 1rem;
        padding: 1rem 1.05rem;
        margin: 0.2rem 0 1rem;
        background:
          linear-gradient(145deg, rgba(38, 24, 74, 0.72), rgba(8, 17, 32, 0.90));
        box-shadow: 0 14px 36px rgba(0, 0, 0, 0.18);
      }}
      .aim-retrieval-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 0.8rem;
      }}
      .aim-retrieval-kicker {{
        color: #C4B5FD;
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: 0.11em;
        text-transform: uppercase;
      }}
      .aim-retrieval-badge {{
        border: 1px solid rgba(34, 197, 94, 0.30);
        border-radius: 999px;
        padding: 0.28rem 0.52rem;
        background: rgba(22, 101, 52, 0.14);
        color: #BBF7D0;
        font-size: 0.68rem;
        font-weight: 760;
      }}
      .aim-retrieval-grid {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0.6rem;
      }}
      .aim-retrieval-item {{
        border: 1px solid rgba(148, 163, 184, 0.14);
        border-radius: 0.78rem;
        padding: 0.68rem 0.72rem;
        background: rgba(15, 23, 42, 0.48);
        min-height: 4.3rem;
      }}
      .aim-retrieval-label {{
        color: #94A3B8;
        font-size: 0.66rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
      }}
      .aim-retrieval-value {{
        color: #F8FAFC;
        font-size: 0.82rem;
        font-weight: 760;
        line-height: 1.35;
        margin-top: 0.26rem;
      }}
      .aim-retrieval-footnote {{
        margin-top: 0.72rem;
        color: #94A3B8;
        font-size: 0.68rem;
        line-height: 1.45;
      }}
      @media (max-width: 900px) {{
        .aim-retrieval-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      }}
      @media (max-width: 560px) {{
        .aim-retrieval-grid {{ grid-template-columns: 1fr; }}
      }}
    </style>
    <section class="aim-retrieval-trace" aria-label="CockroachDB retrieval trace">
      <div class="aim-retrieval-header">
        <span class="aim-retrieval-kicker">CockroachDB retrieval trace</span>
        <span class="aim-retrieval-badge">TRUSTED MEMORY</span>
      </div>
      <div class="aim-retrieval-grid">
        <div class="aim-retrieval-item">
          <div class="aim-retrieval-label">Vector index</div>
          <div class="aim-retrieval-value">Distributed Vector Indexing</div>
        </div>
        <div class="aim-retrieval-item">
          <div class="aim-retrieval-label">Vector space</div>
          <div class="aim-retrieval-value">1,024-D · cosine</div>
        </div>
        <div class="aim-retrieval-item">
          <div class="aim-retrieval-label">Requested Top-K</div>
          <div class="aim-retrieval-value">{_REQUESTED_TOP_K} · application-owned</div>
        </div>
        <div class="aim-retrieval-item">
          <div class="aim-retrieval-label">Returned memories</div>
          <div class="aim-retrieval-value">{returned}</div>
        </div>
        <div class="aim-retrieval-item">
          <div class="aim-retrieval-label">Vector retrieval</div>
          <div class="aim-retrieval-value">{retrieval_time}</div>
        </div>
        <div class="aim-retrieval-item">
          <div class="aim-retrieval-label">Database access</div>
          <div class="aim-retrieval-value">CockroachDB Cloud Managed MCP</div>
        </div>
        <div class="aim-retrieval-item">
          <div class="aim-retrieval-label">Evidence control</div>
          <div class="aim-retrieval-value">Application-validated</div>
        </div>
        <div class="aim-retrieval-item">
          <div class="aim-retrieval-label">Memory admission</div>
          <div class="aim-retrieval-value">Resolved / closed sync path</div>
        </div>
      </div>
      <div class="aim-retrieval-footnote">
        Returned-memory count and vector-retrieval latency are request-derived when available.
        Index, vector, access-path, and control labels describe the reviewed deployment architecture;
        resolved/closed admission is enforced by the controlled synchronization workflow.
      </div>
    </section>
    """


def render_retrieval_trace(result: AnalysisResult) -> None:
    """Show how CockroachDB participated in the completed investigation."""
    st.subheader("CockroachDB Retrieval Trace")
    st.caption("Judge-facing proof of the operational-memory retrieval path.")
    st.html(_retrieval_trace_html(result))
