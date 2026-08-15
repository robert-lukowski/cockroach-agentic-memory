"""Agentic Incident Command Center Streamlit application."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import streamlit as st  # noqa: E402

from frontend.api_client import (  # noqa: E402
    AgenticMemoryApiClient,
    ApiClientError,
    FrontendConfigurationError,
    load_config,
)
from frontend.models import (  # noqa: E402
    DEMO_SCENARIOS,
    InputValidationError,
    InvestigationInput,
    ResponseValidationError,
    normalize_analysis_response,
)
from frontend.ui_components import (  # noqa: E402
    render_demo_corpus_summary,
    render_investigation_explanation,
    render_metrics,
    render_operational_memory_graph,
    render_recommendation,
    render_supporting_incidents,
    render_timings,
    render_transient_retry_status,
    render_verified_security_controls,
)
from frontend.ui_theme import (  # noqa: E402
    apply_command_center_theme,
    render_command_center_hero,
    render_memory_pipeline,
)
from frontend.video_background import render_background_video  # noqa: E402

st.set_page_config(
    page_title="Agentic Incident Memory",
    page_icon="🧠",
    layout="wide",
)


def _secrets() -> dict[str, object]:
    try:
        return dict(st.secrets)
    except Exception:
        return {}


def _load_scenario() -> None:
    scenario_key = st.session_state.get("scenario_key", "custom")
    scenario = next((item for item in DEMO_SCENARIOS if item.key == scenario_key), None)
    values = {
        "incident_number": "",
        "incident_title": "",
        "incident_symptoms": "",
        "incident_service": "",
        "incident_environment": "",
    }
    if scenario is not None:
        values.update(
            {
                "incident_number": scenario.incident_number,
                "incident_title": scenario.title,
                "incident_symptoms": scenario.symptoms,
                "incident_service": scenario.service,
                "incident_environment": scenario.environment,
            }
        )
    st.session_state.update(values)


def _initialize_form() -> None:
    if "incident_title" not in st.session_state:
        st.session_state["scenario_key"] = DEMO_SCENARIOS[0].key
        _load_scenario()


def main() -> None:
    apply_command_center_theme()
    render_background_video()
    render_command_center_hero()
    render_demo_corpus_summary()
    render_memory_pipeline()
    _initialize_form()

    st.subheader("Investigate an active incident")
    st.caption(
        "Load a synthetic scenario or enter your own incident. The active incident is used for "
        "retrieval only and is not written into trusted operational memory."
    )

    scenario_options = {"custom": "Custom incident"} | {
        scenario.key: scenario.label for scenario in DEMO_SCENARIOS
    }
    st.selectbox(
        "Load sample incident",
        options=list(scenario_options),
        format_func=scenario_options.get,
        key="scenario_key",
        on_change=_load_scenario,
    )

    with st.form("investigation_form"):
        title = st.text_input(
            "Incident title / short description *",
            key="incident_title",
            max_chars=256,
        )
        symptoms = st.text_area(
            "Symptoms / description *",
            key="incident_symptoms",
            height=180,
            max_chars=7_900,
        )
        left, middle, right = st.columns(3)
        service = left.text_input("Service", key="incident_service", max_chars=256)
        environment = middle.text_input(
            "Environment",
            key="incident_environment",
            max_chars=64,
        )
        incident_number = right.text_input(
            "Incident number (optional)",
            key="incident_number",
            max_chars=40,
        )
        submitted = st.form_submit_button(
            "⚡ Run Agentic Investigation",
            type="primary",
            use_container_width=True,
        )

    if not submitted:
        st.info("Choose a synthetic scenario or enter an incident, then run the investigation.")
        return

    try:
        request = InvestigationInput(
            title=title,
            symptoms=symptoms,
            service=service,
            environment=environment,
            incident_number=incident_number,
        )
        payload = request.to_api_payload()
        config = load_config(secrets=_secrets())
        with st.spinner("Retrieving incident memory and generating a recommendation…"):
            api_result = AgenticMemoryApiClient(config).analyze(payload)
            result = normalize_analysis_response(api_result.payload)
    except InputValidationError as error:
        st.error(str(error))
        return
    except FrontendConfigurationError as error:
        st.error("The frontend is not configured for the analysis API.")
        with st.expander("Sanitized technical details"):
            st.text(str(error))
        return
    except ApiClientError as error:
        st.error("The investigation service could not complete the request.")
        with st.expander("Sanitized technical details"):
            st.text(f"Category: {error.category}")
            if error.status is not None:
                st.text(f"HTTP status: {error.status}")
        return
    except ResponseValidationError as error:
        st.error("The investigation service returned an incomplete response.")
        with st.expander("Sanitized technical details"):
            st.text(str(error))
        return

    st.divider()
    render_transient_retry_status(
        transient_retry_occurred=api_result.transient_retry_occurred
    )
    render_metrics(result, round_trip_ms=api_result.round_trip_ms)
    render_recommendation(result)
    render_investigation_explanation()
    render_operational_memory_graph(
        result,
        current_incident_number=incident_number,
        current_service=service,
    )
    render_timings(result)
    render_supporting_incidents(result)
    render_verified_security_controls()


if __name__ == "__main__":
    main()
