"""Reusable Streamlit rendering helpers."""

from __future__ import annotations

from html import escape

import plotly.graph_objects as go
import streamlit as st

from frontend.graph import GraphNode, OperationalMemoryGraph, build_operational_memory_graph
from frontend.models import AnalysisResult, format_milliseconds, format_percentage
from frontend.security_controls import VERIFIED_SECURITY_CONTROLS

DEMO_CORPUS_METRICS = (
    ("ServiceNow Incidents", 60),
    ("Resolved Memories", 50),
    ("Active Scenarios", 10),
    ("Top-K Evidence", 5),
)
ARCHITECTURE_GITHUB_URL = (
    "https://github.com/robert-lukowski/cockroach-agentic-memory#architecture"
)
AUTOMATION_GITHUB_URL = (
    "https://github.com/robert-lukowski/cockroach-agentic-memory/"
    "actions/workflows/generate-demo-incident.yml"
)


def render_demo_corpus_summary() -> None:
    st.subheader("Demo Operational Memory")
    columns = st.columns(len(DEMO_CORPUS_METRICS))
    for column, (label, value) in zip(columns, DEMO_CORPUS_METRICS, strict=True):
        column.metric(label, str(value))
    st.caption("Static demo corpus used by the current hackathon environment.")


def render_metrics(result: AnalysisResult, *, round_trip_ms: float) -> None:
    columns = st.columns(3)
    columns[0].metric("Best semantic match", format_percentage(result.best_similarity))
    columns[1].metric("Supporting incidents", str(result.supporting_count))
    columns[2].metric("Client-observed round trip", format_milliseconds(round_trip_ms))


def render_transient_retry_status(*, transient_retry_occurred: bool) -> None:
    if transient_retry_occurred:
        st.info("Transient backend dependency failure detected. Automatic retry succeeded.")


def _recommendation_html(result: AnalysisResult) -> str:
    safe_recommendation = escape(result.recommendation).replace("\n", "<br>")
    supporting = str(result.supporting_count)
    return f"""
    <section class="aim-recommendation" aria-label="Grounded Bedrock recommendation">
      <div class="aim-rec-header">
        <div>
          <div class="aim-rec-eyebrow">Grounded analysis output</div>
          <div class="aim-rec-title">Bedrock Recommendation</div>
        </div>
        <div class="aim-rec-badge">Validated evidence</div>
      </div>
      <div class="aim-rec-body">{safe_recommendation}</div>
      <div class="aim-rec-provenance" aria-label="Recommendation provenance">
        <span class="aim-provenance-pill">CockroachDB memory</span>
        <span class="aim-provenance-pill">{supporting} supporting incidents</span>
      </div>
    </section>
    """


def render_recommendation(result: AnalysisResult) -> None:
    st.subheader("Recommendation")
    st.html(_recommendation_html(result))


def render_investigation_explanation() -> None:
    st.subheader("What just happened?")
    st.markdown(
        "**Current Incident** → **Titan Embedding** → **CockroachDB Retrieval** → "
        "**Validated Top-5 Evidence** → **Bedrock Recommendation**"
    )
    st.markdown(
        "1. Current incident symptoms were converted into a Titan embedding.\n"
        "2. CockroachDB searched the resolved operational-memory corpus for semantically "
        "similar incidents.\n"
        "3. The application selected and validated up to 5 historical resolved memories.\n"
        "4. Only the controlled current symptoms and validated historical evidence were "
        "provided to Amazon Bedrock.\n"
        "5. Bedrock generated the grounded diagnosis and recommended actions shown above."
    )
    st.caption(
        "Architecture explanation — the timing values shown in Execution Telemetry are live "
        "per-request measurements; this stage description is not a distributed trace."
    )
    st.caption(
        "Trust boundary: Streamlit calls the application API; it does not connect directly to "
        "CockroachDB or Bedrock. The application owns the memory scope, fixed retrieval, evidence "
        "validation, and returned incident IDs. Bedrock does not choose SQL, scope, or IDs. Only "
        "resolved or closed incidents become memory; this active incident was not stored."
    )
    architecture, automation = st.columns(2)
    architecture.link_button(
        "View Architecture on GitHub",
        ARCHITECTURE_GITHUB_URL,
        use_container_width=True,
    )
    automation.link_button(
        "View Automation on GitHub",
        AUTOMATION_GITHUB_URL,
        use_container_width=True,
    )


def _execution_telemetry_html(result: AnalysisResult) -> str:
    timing_definitions = (
        ("vector_retrieval_ms", "Vector retrieval", "CockroachDB evidence lookup"),
        ("bedrock_inference_ms", "Bedrock inference", "Grounded recommendation generation"),
        ("total_request_ms", "Backend total", "Application-side request processing"),
    )
    available = [
        (key, label, detail, float(result.timings[key]))
        for key, label, detail in timing_definitions
        if key in result.timings
    ]
    if not available:
        return ""

    maximum = max(max(value, 0.0) for _key, _label, _detail, value in available)
    rows: list[str] = []
    for _key, label, detail, raw_value in available:
        value = max(raw_value, 0.0)
        width = 0.0 if maximum <= 0.0 else (value / maximum) * 100.0
        rows.append(
            f"""
            <div class="aim-telemetry-row">
              <div class="aim-telemetry-label">
                <strong>{label}</strong>
                <span>{detail}</span>
              </div>
              <div class="aim-telemetry-track" aria-hidden="true">
                <span class="aim-telemetry-fill" style="width:{width:.1f}%"></span>
              </div>
              <div class="aim-telemetry-value">{format_milliseconds(value)}</div>
            </div>
            """
        )

    return f"""
    <style>
      .aim-telemetry-panel {{
        border: 1px solid rgba(56, 189, 248, 0.22);
        border-radius: 1rem;
        padding: 1rem 1.05rem;
        margin: 0.2rem 0 1rem;
        background:
          linear-gradient(145deg, rgba(15, 23, 42, 0.90), rgba(8, 17, 32, 0.84));
        box-shadow: 0 14px 36px rgba(0, 0, 0, 0.18);
      }}

      .aim-telemetry-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 0.75rem;
      }}

      .aim-telemetry-header span:first-child {{
        color: #BAE6FD;
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: 0.11em;
        text-transform: uppercase;
      }}

      .aim-telemetry-badge {{
        border: 1px solid rgba(34, 197, 94, 0.28);
        border-radius: 999px;
        padding: 0.28rem 0.52rem;
        background: rgba(22, 101, 52, 0.14);
        color: #BBF7D0;
        font-size: 0.68rem;
        font-weight: 720;
      }}

      .aim-telemetry-row {{
        display: grid;
        grid-template-columns: minmax(180px, 0.9fr) minmax(220px, 1.6fr) auto;
        gap: 0.85rem;
        align-items: center;
        padding: 0.58rem 0;
        border-top: 1px solid rgba(148, 163, 184, 0.10);
      }}

      .aim-telemetry-label {{
        display: flex;
        flex-direction: column;
        gap: 0.12rem;
      }}

      .aim-telemetry-label strong {{
        color: #F8FAFC;
        font-size: 0.86rem;
      }}

      .aim-telemetry-label span {{
        color: #94A3B8;
        font-size: 0.70rem;
      }}

      .aim-telemetry-track {{
        height: 0.46rem;
        overflow: hidden;
        border-radius: 999px;
        background: rgba(148, 163, 184, 0.12);
      }}

      .aim-telemetry-fill {{
        display: block;
        height: 100%;
        min-width: 0.35rem;
        border-radius: 999px;
        background: linear-gradient(90deg, #2563EB, #38BDF8);
        box-shadow: 0 0 14px rgba(56, 189, 248, 0.24);
      }}

      .aim-telemetry-value {{
        min-width: 5.6rem;
        color: #E2E8F0;
        font-size: 0.82rem;
        font-weight: 750;
        text-align: right;
        font-variant-numeric: tabular-nums;
      }}

      .aim-telemetry-footnote {{
        margin-top: 0.62rem;
        color: #94A3B8;
        font-size: 0.68rem;
        line-height: 1.45;
      }}

      @media (max-width: 760px) {{
        .aim-telemetry-row {{
          grid-template-columns: 1fr auto;
        }}
        .aim-telemetry-track {{
          grid-column: 1 / -1;
          grid-row: 2;
        }}
      }}
    </style>
    <section class="aim-telemetry-panel" aria-label="Per-request execution telemetry">
      <div class="aim-telemetry-header">
        <span>Backend execution path</span>
        <span class="aim-telemetry-badge">PER REQUEST</span>
      </div>
      {''.join(rows)}
      <div class="aim-telemetry-footnote">
        Backend timings are returned by the analysis service. Client-observed round trip above
        also includes network time and any single transient retry delay.
      </div>
    </section>
    """


def render_timings(result: AnalysisResult) -> None:
    telemetry_html = _execution_telemetry_html(result)
    if not telemetry_html:
        return
    st.subheader("Execution Telemetry")
    st.caption("Measured timing from the completed investigation request.")
    st.html(telemetry_html)


def _node_hover(node: GraphNode) -> str:
    if node.is_current:
        lines = ["<b>Current Incident</b>"]
        if node.identifier:
            lines.append(f"Incident: {escape(node.identifier)}")
        if node.service:
            lines.append(f"Service: {escape(node.service)}")
        return "<br>".join(lines)

    lines = [f"<b>{escape(node.identifier)}</b>"]
    if node.service:
        lines.append(f"Service: {escape(node.service)}")
    if node.similarity is not None:
        lines.append(f"Semantic similarity: {node.similarity:.1%}")
    if node.root_cause:
        lines.append(f"Root cause: {escape(node.root_cause)}")
    if node.resolution:
        lines.append(f"Resolution: {escape(node.resolution)}")
    return "<br>".join(lines)


def build_operational_memory_figure(graph: OperationalMemoryGraph) -> go.Figure:
    """Render normalized graph data without deriving new relationships."""
    positions = {node.node_id: node for node in graph.nodes}
    figure = go.Figure()
    for edge in graph.edges:
        source = positions[edge.source_id]
        target = positions[edge.target_id]
        similarity = edge.similarity
        width = 1.5 if similarity is None else 1.5 + (3.5 * similarity)
        opacity = 0.35 if similarity is None else 0.35 + (0.55 * similarity)
        figure.add_trace(
            go.Scatter(
                x=[source.x, target.x],
                y=[source.y, target.y],
                mode="lines",
                line={"width": width, "color": f"rgba(56,189,248,{opacity:.3f})"},
                hoverinfo="skip",
                showlegend=False,
            )
        )

    current_nodes = [node for node in graph.nodes if node.is_current]
    historical_nodes = [node for node in graph.nodes if not node.is_current]
    for nodes, color, size, symbol, border, name in (
        (current_nodes, "#F97316", 35, "diamond", "#FED7AA", "Current Incident"),
        (historical_nodes, "#38BDF8", 24, "circle", "#BAE6FD", "Resolved Memory"),
    ):
        if not nodes:
            continue
        figure.add_trace(
            go.Scatter(
                x=[node.x for node in nodes],
                y=[node.y for node in nodes],
                mode="markers+text",
                text=[escape(node.label).replace("\n", "<br>") for node in nodes],
                textposition="bottom center",
                textfont={"color": "#E5E7EB", "size": 12},
                hovertext=[_node_hover(node) for node in nodes],
                hoverinfo="text",
                marker={
                    "size": size,
                    "color": color,
                    "symbol": symbol,
                    "opacity": 0.96,
                    "line": {"width": 2.2, "color": border},
                },
                name=name,
                showlegend=True,
            )
        )
    figure.update_layout(
        height=520,
        margin={"l": 25, "r": 25, "t": 58, "b": 48},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, ui-sans-serif, system-ui", "color": "#E5E7EB"},
        hoverlabel={
            "bgcolor": "#0F172A",
            "bordercolor": "#38BDF8",
            "font": {"color": "#F8FAFC", "size": 12},
        },
        xaxis={"visible": False, "range": [-1.55, 1.55], "fixedrange": True},
        yaxis={"visible": False, "range": [-1.55, 1.55], "fixedrange": True},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.01,
            "xanchor": "right",
            "x": 1.0,
            "bgcolor": "rgba(0,0,0,0)",
            "font": {"color": "#CBD5E1", "size": 11},
        },
        showlegend=True,
    )
    return figure


def _memory_graph_context_html(result: AnalysisResult) -> str:
    return f"""
    <div class="aim-graph-context" aria-label="Operational memory retrieval summary">
      <div>
        <span class="aim-graph-kicker">CockroachDB retrieval</span>
        <strong>Evidence map</strong>
      </div>
      <div class="aim-graph-stats">
        <span>{result.supporting_count} memories</span>
        <span>Best match {format_percentage(result.best_similarity)}</span>
      </div>
    </div>
    """


def render_operational_memory_graph(
    result: AnalysisResult,
    *,
    current_incident_number: str,
    current_service: str,
) -> None:
    st.subheader("Operational Memory Graph")
    st.caption(
        "Semantic links from the current incident to resolved operational memory retrieved "
        "from CockroachDB."
    )
    graph = build_operational_memory_graph(
        result,
        current_incident_number=current_incident_number,
        current_service=current_service,
    )
    if graph.state == "legacy":
        st.info(
            "Graph visualization requires structured historical memory; legacy incident IDs "
            "remain available below."
        )
        return
    if graph.state == "empty":
        st.info("No supporting operational memory is available to visualize.")
        return
    st.html(_memory_graph_context_html(result))
    st.plotly_chart(
        build_operational_memory_figure(graph),
        width="stretch",
        theme=None,
        config={"displayModeBar": False, "scrollZoom": False},
    )


def render_supporting_incidents(result: AnalysisResult) -> None:
    st.subheader("Supporting incidents")
    if result.supporting_incidents:
        for index, incident in enumerate(result.supporting_incidents, start=1):
            similarity = format_percentage(incident.similarity)
            with st.expander(
                f"{index}. {incident.display_identifier} · {incident.service} · {similarity}",
                expanded=index == 1,
            ):
                st.caption(f"Semantic similarity: {similarity}")
                st.markdown("**Root cause**")
                st.text(incident.root_cause or "Not available")
                st.markdown("**Resolution**")
                st.text(incident.resolution or "Not available")
        return
    if result.legacy_incident_ids:
        st.info("Readable incident details are unavailable in this legacy response.")
        for index, incident_id in enumerate(result.legacy_incident_ids, start=1):
            st.text(f"{index}. {incident_id}")
        return
    st.info("No supporting incidents were returned for this investigation.")


def render_verified_security_controls() -> None:
    st.divider()
    st.subheader("Verified Security Controls")
    st.caption(
        "Architecture controls verified from the deployed project configuration; this panel "
        "is not live request telemetry."
    )
    columns = st.columns(3)
    for index, control in enumerate(VERIFIED_SECURITY_CONTROLS):
        with columns[index % len(columns)]:
            with st.container(border=True):
                st.markdown(f"**{control.name}**")
                st.success(f"Status: {control.status}")
                st.caption(control.description)
