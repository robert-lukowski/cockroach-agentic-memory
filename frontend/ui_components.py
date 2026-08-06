"""Reusable Streamlit rendering helpers."""

from __future__ import annotations

import streamlit as st

from frontend.models import AnalysisResult, format_milliseconds, format_percentage


def render_metrics(result: AnalysisResult, *, round_trip_ms: float) -> None:
    columns = st.columns(4)
    columns[0].metric("Best semantic match", format_percentage(result.best_similarity))
    columns[1].metric("Supporting incidents", str(result.supporting_count))
    columns[2].metric("Confidence", format_percentage(result.confidence))
    backend_total = result.timings.get("total_request_ms")
    columns[3].metric(
        "Total response time" if backend_total is not None else "Client round trip",
        format_milliseconds(backend_total if backend_total is not None else round_trip_ms),
    )


def render_recommendation(result: AnalysisResult) -> None:
    st.subheader("Recommendation")
    st.text(result.recommendation)


def render_timings(result: AnalysisResult, *, round_trip_ms: float) -> None:
    if not result.timings:
        st.caption(f"Client round trip: {format_milliseconds(round_trip_ms)}")
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
        st.caption(f"Client round trip: {format_milliseconds(round_trip_ms)}")


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
