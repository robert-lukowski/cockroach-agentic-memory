"""Reusable Streamlit rendering helpers."""

from __future__ import annotations

from html import escape

import plotly.graph_objects as go
import streamlit as st

from frontend.graph import GraphNode, OperationalMemoryGraph, build_operational_memory_graph
from frontend.models import AnalysisResult, format_milliseconds, format_percentage
from frontend.security_controls import VERIFIED_SECURITY_CONTROLS


def render_metrics(result: AnalysisResult, *, round_trip_ms: float) -> None:
    columns = st.columns(4)
    columns[0].metric("Best semantic match", format_percentage(result.best_similarity))
    columns[1].metric("Supporting incidents", str(result.supporting_count))
    columns[2].metric("Confidence", format_percentage(result.confidence))
    columns[3].metric("Client-observed round trip", format_milliseconds(round_trip_ms))


def render_transient_retry_status(*, transient_retry_occurred: bool) -> None:
    if transient_retry_occurred:
        st.info("Transient backend dependency failure detected. Automatic retry succeeded.")


def render_recommendation(result: AnalysisResult) -> None:
    st.subheader("Recommendation")
    st.text(result.recommendation)


def render_timings(result: AnalysisResult) -> None:
    if not result.timings:
        return
    labels = {
        "vector_retrieval_ms": "Vector retrieval",
        "bedrock_inference_ms": "Bedrock inference",
        "total_request_ms": "Total request",
    }
    with st.expander("Timing details"):
        for key, label in labels.items():
            if key in result.timings:
                st.write(f"{label}: {format_milliseconds(result.timings[key])}")


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
    for nodes, color, size, name in (
        (current_nodes, "#F97316", 31, "Current Incident"),
        (historical_nodes, "#38BDF8", 23, "Resolved Memory"),
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
                    "line": {"width": 2, "color": "#E5E7EB"},
                },
                name=name,
                showlegend=True,
            )
        )
    figure.update_layout(
        height=500,
        margin={"l": 25, "r": 25, "t": 50, "b": 45},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel={"bgcolor": "#151D31", "font": {"color": "#E5E7EB"}},
        xaxis={"visible": False, "range": [-1.55, 1.55], "fixedrange": True},
        yaxis={"visible": False, "range": [-1.55, 1.55], "fixedrange": True},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.01,
            "xanchor": "right",
            "x": 1.0,
            "bgcolor": "rgba(0,0,0,0)",
            "font": {"color": "#E5E7EB", "size": 11},
        },
        showlegend=True,
    )
    return figure


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
