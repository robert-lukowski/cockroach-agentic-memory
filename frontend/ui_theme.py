"""Visual theme helpers for the Streamlit command center.

This module contains presentation-only HTML/CSS. It intentionally does not
change investigation logic, API behavior, or operational-memory semantics.
"""

from __future__ import annotations

import streamlit as st


_COMMAND_CENTER_CSS = r"""
<style>
:root {
  --aim-cyan: #38BDF8;
  --aim-cyan-soft: rgba(56, 189, 248, 0.16);
  --aim-blue: #2563EB;
  --aim-orange: #F97316;
  --aim-surface: rgba(21, 29, 49, 0.72);
  --aim-surface-strong: rgba(15, 23, 42, 0.92);
  --aim-border: rgba(148, 163, 184, 0.18);
  --aim-text-muted: #94A3B8;
}

/* Page background: lightweight CSS instead of autoplay video. */
[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(circle at 14% 8%, rgba(37, 99, 235, 0.17), transparent 30%),
    radial-gradient(circle at 88% 14%, rgba(56, 189, 248, 0.12), transparent 28%),
    linear-gradient(180deg, #07101F 0%, #0B1020 42%, #080D18 100%);
}

[data-testid="stAppViewContainer"]::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  opacity: 0.23;
  background-image:
    linear-gradient(rgba(56, 189, 248, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(56, 189, 248, 0.06) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: linear-gradient(to bottom, black, transparent 80%);
  z-index: 0;
}

[data-testid="stMainBlockContainer"] {
  position: relative;
  z-index: 1;
  max-width: 1320px;
  padding-top: 2rem;
}

/* Native Streamlit metric cards. */
[data-testid="stMetric"] {
  background: linear-gradient(145deg, rgba(21, 29, 49, 0.90), rgba(10, 17, 31, 0.82));
  border: 1px solid var(--aim-border);
  border-radius: 1rem;
  padding: 1rem 1.05rem;
  min-height: 112px;
  box-shadow: 0 14px 35px rgba(0, 0, 0, 0.20);
  transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
}

[data-testid="stMetric"]:hover {
  transform: translateY(-3px);
  border-color: rgba(56, 189, 248, 0.45);
  box-shadow: 0 16px 42px rgba(0, 0, 0, 0.27), 0 0 0 1px rgba(56, 189, 248, 0.05);
}

[data-testid="stMetricLabel"] {
  color: var(--aim-text-muted);
  letter-spacing: 0.02em;
}

[data-testid="stMetricValue"] {
  color: #F8FAFC;
  font-weight: 760;
}

/* Forms and expandable evidence panels. */
[data-testid="stForm"],
[data-testid="stExpander"] {
  background: linear-gradient(145deg, rgba(21, 29, 49, 0.78), rgba(10, 17, 31, 0.72));
  border: 1px solid var(--aim-border) !important;
  border-radius: 1rem !important;
  box-shadow: 0 12px 34px rgba(0, 0, 0, 0.16);
}

[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stSelectbox"] > div > div {
  background: rgba(6, 12, 24, 0.74) !important;
}

/* Primary investigation CTA. */
div[data-testid="stFormSubmitButton"] button[kind="primary"],
div.stButton > button[kind="primary"] {
  min-height: 3.15rem;
  border: 1px solid rgba(125, 211, 252, 0.65);
  background: linear-gradient(100deg, #0284C7 0%, #2563EB 52%, #0EA5E9 100%);
  background-size: 180% 180%;
  color: white;
  font-weight: 750;
  letter-spacing: 0.015em;
  box-shadow: 0 12px 28px rgba(14, 165, 233, 0.23);
  transition: transform 170ms ease, box-shadow 170ms ease, filter 170ms ease;
  animation: aim-gradient-drift 7s ease infinite;
}

div[data-testid="stFormSubmitButton"] button[kind="primary"]:hover,
div.stButton > button[kind="primary"]:hover {
  transform: translateY(-2px);
  filter: brightness(1.08);
  box-shadow: 0 16px 34px rgba(14, 165, 233, 0.31);
}

/* Link buttons get a quieter enterprise treatment. */
[data-testid="stLinkButton"] a {
  border-color: rgba(56, 189, 248, 0.28) !important;
  background: rgba(15, 23, 42, 0.68) !important;
  transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
}

[data-testid="stLinkButton"] a:hover {
  transform: translateY(-2px);
  border-color: rgba(56, 189, 248, 0.56) !important;
  background: rgba(30, 41, 59, 0.90) !important;
}

/* Plotly sits inside the same visual language as the rest of the command center. */
[data-testid="stPlotlyChart"] {
  border: 1px solid var(--aim-border);
  border-radius: 1rem;
  background:
    radial-gradient(circle at 50% 50%, rgba(14, 165, 233, 0.06), transparent 48%),
    rgba(7, 16, 31, 0.56);
  padding: 0.35rem;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02), 0 14px 38px rgba(0, 0, 0, 0.16);
}

/* Headings and dividers. */
h1, h2, h3 {
  letter-spacing: -0.025em;
}

hr {
  border-color: rgba(148, 163, 184, 0.12) !important;
}

/* Hero */
.aim-hero {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 1.35rem;
  padding: 2rem 2rem 1.75rem;
  margin: 0 0 1.35rem;
  background:
    radial-gradient(circle at 84% 14%, rgba(56, 189, 248, 0.18), transparent 32%),
    radial-gradient(circle at 12% 84%, rgba(37, 99, 235, 0.16), transparent 34%),
    linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(8, 15, 29, 0.94));
  box-shadow: 0 22px 55px rgba(0, 0, 0, 0.26);
}

.aim-hero::after {
  content: "";
  position: absolute;
  width: 360px;
  height: 360px;
  border-radius: 999px;
  top: -255px;
  right: -80px;
  border: 1px solid rgba(56, 189, 248, 0.18);
  box-shadow: 0 0 80px rgba(56, 189, 248, 0.10);
  animation: aim-orbit 11s ease-in-out infinite alternate;
}

.aim-eyebrow {
  color: #7DD3FC;
  font-size: 0.76rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  margin-bottom: 0.55rem;
}

.aim-hero h1 {
  margin: 0;
  max-width: 900px;
  color: #F8FAFC;
  font-size: clamp(2rem, 5vw, 3.75rem);
  line-height: 1.02;
  letter-spacing: -0.055em;
}

.aim-hero p {
  max-width: 880px;
  margin: 0.85rem 0 1.15rem;
  color: #CBD5E1;
  font-size: 1.03rem;
  line-height: 1.65;
}

.aim-status-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
}

.aim-status {
  display: inline-flex;
  align-items: center;
  gap: 0.44rem;
  padding: 0.45rem 0.7rem;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.68);
  color: #DDE7F2;
  font-size: 0.78rem;
  font-weight: 650;
}

.aim-dot {
  width: 0.47rem;
  height: 0.47rem;
  border-radius: 999px;
  background: #38BDF8;
  box-shadow: 0 0 12px rgba(56, 189, 248, 0.80);
}

/* Compact memory pipeline shown before the incident form. */
.aim-pipeline {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 0.6rem;
  align-items: stretch;
  margin: 0.15rem 0 1.3rem;
}

.aim-stage {
  position: relative;
  min-height: 84px;
  padding: 0.78rem 0.72rem;
  border: 1px solid var(--aim-border);
  border-radius: 0.85rem;
  background: rgba(15, 23, 42, 0.62);
  transition: transform 170ms ease, border-color 170ms ease, background 170ms ease;
}

.aim-stage:hover {
  transform: translateY(-3px);
  border-color: rgba(56, 189, 248, 0.46);
  background: rgba(21, 34, 57, 0.82);
}

.aim-stage-kicker {
  color: #7DD3FC;
  font-size: 0.67rem;
  font-weight: 780;
  letter-spacing: 0.10em;
  text-transform: uppercase;
}

.aim-stage-title {
  margin-top: 0.25rem;
  color: #F8FAFC;
  font-size: 0.86rem;
  line-height: 1.25;
  font-weight: 720;
}

.aim-stage:not(:last-child)::after {
  content: "→";
  position: absolute;
  right: -0.52rem;
  top: 50%;
  transform: translate(50%, -50%);
  z-index: 2;
  color: rgba(125, 211, 252, 0.78);
  font-size: 1.05rem;
}

/* Recommendation is the product's primary value, so give it visual priority. */
.aim-recommendation {
  position: relative;
  overflow: hidden;
  margin: 0.25rem 0 1.1rem;
  padding: 1.35rem 1.45rem 1.25rem;
  border: 1px solid rgba(56, 189, 248, 0.30);
  border-radius: 1.1rem;
  background:
    radial-gradient(circle at 92% 10%, rgba(56, 189, 248, 0.13), transparent 30%),
    linear-gradient(145deg, rgba(15, 23, 42, 0.95), rgba(8, 17, 32, 0.92));
  box-shadow: 0 20px 46px rgba(0, 0, 0, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.025);
  transition: border-color 180ms ease, box-shadow 180ms ease;
}

.aim-recommendation:hover {
  border-color: rgba(56, 189, 248, 0.52);
  box-shadow: 0 22px 52px rgba(0, 0, 0, 0.27), 0 0 34px rgba(14, 165, 233, 0.05);
}

.aim-recommendation::before {
  content: "";
  position: absolute;
  left: 0;
  top: 1rem;
  bottom: 1rem;
  width: 3px;
  border-radius: 999px;
  background: linear-gradient(180deg, #38BDF8, #2563EB, #F97316);
  box-shadow: 0 0 16px rgba(56, 189, 248, 0.28);
}

.aim-rec-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.aim-rec-eyebrow,
.aim-graph-kicker {
  color: #7DD3FC;
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.aim-rec-title {
  margin-top: 0.2rem;
  color: #F8FAFC;
  font-size: 1.18rem;
  font-weight: 780;
  letter-spacing: -0.025em;
}

.aim-rec-badge {
  flex: 0 0 auto;
  padding: 0.4rem 0.65rem;
  border: 1px solid rgba(34, 197, 94, 0.28);
  border-radius: 999px;
  background: rgba(22, 101, 52, 0.16);
  color: #BBF7D0;
  font-size: 0.72rem;
  font-weight: 720;
}

.aim-rec-body {
  color: #E2E8F0;
  font-size: 0.97rem;
  line-height: 1.68;
  white-space: normal;
}

.aim-rec-provenance {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 1.15rem;
  padding-top: 0.9rem;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
}

.aim-provenance-pill {
  display: inline-flex;
  padding: 0.34rem 0.58rem;
  border: 1px solid rgba(56, 189, 248, 0.18);
  border-radius: 999px;
  background: rgba(14, 165, 233, 0.07);
  color: #BAE6FD;
  font-size: 0.7rem;
  font-weight: 650;
}

/* A compact bridge between retrieval metrics and the interactive graph. */
.aim-graph-context {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin: 0.35rem 0 0.7rem;
  padding: 0.78rem 0.9rem;
  border: 1px solid rgba(56, 189, 248, 0.17);
  border-radius: 0.85rem;
  background: rgba(15, 23, 42, 0.52);
}

.aim-graph-context strong {
  display: block;
  margin-top: 0.1rem;
  color: #F8FAFC;
  font-size: 0.94rem;
}

.aim-graph-stats {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.45rem;
}

.aim-graph-stats span {
  padding: 0.32rem 0.52rem;
  border-radius: 999px;
  background: rgba(56, 189, 248, 0.08);
  color: #CBD5E1;
  font-size: 0.7rem;
  font-weight: 650;
}

/* Respect OS accessibility preference. */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
  }
}

@media (max-width: 900px) {
  [data-testid="stMainBlockContainer"] {
    padding-top: 1rem;
  }
  .aim-hero {
    padding: 1.4rem 1.2rem;
  }
  .aim-pipeline {
    grid-template-columns: 1fr;
  }
  .aim-stage:not(:last-child)::after {
    content: "↓";
    right: 50%;
    top: auto;
    bottom: -0.65rem;
    transform: translate(50%, 50%);
  }
  .aim-rec-header,
  .aim-graph-context {
    align-items: flex-start;
    flex-direction: column;
  }
  .aim-graph-stats {
    justify-content: flex-start;
  }
}

@keyframes aim-gradient-drift {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}

@keyframes aim-orbit {
  from { transform: translate3d(0, 0, 0) scale(1); }
  to { transform: translate3d(-28px, 22px, 0) scale(1.05); }
}
</style>
"""


def apply_command_center_theme() -> None:
    """Apply presentation-only CSS to the current Streamlit page."""
    st.html(_COMMAND_CENTER_CSS)


def render_command_center_hero() -> None:
    """Render the primary product hero without using executable JavaScript."""
    st.html(
        """
        <section class="aim-hero" aria-label="Agentic Incident Memory overview">
          <div class="aim-eyebrow">Persistent operational memory · CockroachDB × AWS</div>
          <h1>Agentic Incident Memory</h1>
          <p>
            Turn verified resolutions into reusable operational intelligence. Investigate an
            active incident against semantically similar CockroachDB memory and generate a
            grounded Amazon Bedrock recommendation.
          </p>
          <div class="aim-status-row" aria-label="Architecture status">
            <span class="aim-status"><span class="aim-dot"></span>AWS agentic backend</span>
            <span class="aim-status"><span class="aim-dot"></span>CockroachDB vector memory</span>
            <span class="aim-status"><span class="aim-dot"></span>Bedrock grounded response</span>
            <span class="aim-status"><span class="aim-dot"></span>ServiceNow workflow ready</span>
          </div>
        </section>
        """
    )


def render_memory_pipeline() -> None:
    """Render a compact visual explanation of the investigation path."""
    st.html(
        """
        <div class="aim-pipeline" aria-label="Agentic investigation pipeline">
          <div class="aim-stage">
            <div class="aim-stage-kicker">01 · Input</div>
            <div class="aim-stage-title">Current Incident</div>
          </div>
          <div class="aim-stage">
            <div class="aim-stage-kicker">02 · Embed</div>
            <div class="aim-stage-title">Titan Embedding</div>
          </div>
          <div class="aim-stage">
            <div class="aim-stage-kicker">03 · Recall</div>
            <div class="aim-stage-title">CockroachDB Retrieval</div>
          </div>
          <div class="aim-stage">
            <div class="aim-stage-kicker">04 · Validate</div>
            <div class="aim-stage-title">Top-5 Verified Evidence</div>
          </div>
          <div class="aim-stage">
            <div class="aim-stage-kicker">05 · Reason</div>
            <div class="aim-stage-title">Bedrock Recommendation</div>
          </div>
        </div>
        """
    )