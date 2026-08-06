"""Tests for Streamlit entrypoint bootstrap behavior."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

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
