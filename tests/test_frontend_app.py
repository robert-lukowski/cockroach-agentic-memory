"""Tests for Streamlit entrypoint bootstrap behavior."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

from frontend.api_client import AgenticMemoryApiClient, ApiCallResult
from frontend.models import DEMO_SCENARIOS

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPOSITORY_ROOT / "frontend" / "app.py"


def _widget_value(elements, label: str):
    return next(item.value for item in elements if item.label == label)


def test_entrypoint_runs_outside_repository_root(tmp_path: Path) -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    for name in tuple(environment):
        if name.startswith(("COV_CORE_", "COVERAGE_")):
            environment.pop(name)

    completed = subprocess.run(
        [sys.executable, str(ENTRYPOINT)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "No module named 'frontend'" not in completed.stderr


def test_custom_incident_is_first_and_clears_sample_values() -> None:
    app = AppTest.from_file(ENTRYPOINT, default_timeout=20).run()

    corpus_metrics = {(metric.label, str(metric.value)) for metric in app.metric}
    assert corpus_metrics >= {
        ("ServiceNow Incidents", "60"),
        ("Resolved Memories", "50"),
        ("Active Scenarios", "10"),
        ("Top-K Evidence", "5"),
    }
    selector = app.selectbox[0]
    assert selector.label == "Load sample incident"
    assert selector.options[0] == "Custom incident"

    selector.select("custom").run()

    assert _widget_value(app.text_input, "Incident title / short description *") == ""
    assert _widget_value(app.text_area, "Symptoms / description *") == ""
    assert _widget_value(app.text_input, "Service") == ""
    assert _widget_value(app.text_input, "Environment") == ""
    assert _widget_value(app.text_input, "Incident number (optional)") == ""
    assert not app.exception


def test_selecting_sample_still_populates_its_values() -> None:
    app = AppTest.from_file(ENTRYPOINT, default_timeout=20).run()
    scenario = DEMO_SCENARIOS[1]

    app.selectbox[0].select("custom").run()
    app.selectbox[0].select(scenario.key).run()

    assert _widget_value(app.text_input, "Incident title / short description *") == scenario.title
    assert _widget_value(app.text_area, "Symptoms / description *") == scenario.symptoms
    assert _widget_value(app.text_input, "Service") == scenario.service
    assert _widget_value(app.text_input, "Environment") == scenario.environment
    assert _widget_value(app.text_input, "Incident number (optional)") == scenario.incident_number
    assert not app.exception


def test_success_layout_places_explanation_between_recommendation_and_graph() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")

    recommendation = source.index("render_recommendation(result)")
    explanation = source.index("render_investigation_explanation()")
    graph = source.index("render_operational_memory_graph(")

    assert recommendation < explanation < graph


def test_successful_investigation_renders_explanation_and_existing_panels(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "AGENTIC_MEMORY_API_ENDPOINT",
        "https://example.test/v1/servicenow/analyze",
    )
    monkeypatch.setenv("AGENTIC_MEMORY_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(
        AgenticMemoryApiClient,
        "analyze",
        lambda _client, _payload: ApiCallResult(
            payload={
                "recommendation": "Inspect the validated synthetic evidence.",
                "supporting_incident_ids": [],
                "supporting_incidents": [],
            },
            round_trip_ms=25.0,
            transient_retry_occurred=False,
        ),
    )
    app = AppTest.from_file(ENTRYPOINT, default_timeout=20).run()

    assert "What just happened?" not in [item.value for item in app.subheader]
    app.button[0].click().run()

    headings = [item.value for item in app.subheader]
    assert headings.index("Recommendation") < headings.index("What just happened?")
    assert headings.index("What just happened?") < headings.index(
        "Operational Memory Graph"
    )
    assert "Verified Security Controls" in headings
    assert not app.exception
