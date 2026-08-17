"""Tests for the judge-facing Streamlit application."""

from __future__ import annotations

import hashlib
from pathlib import Path

from streamlit.testing.v1 import AppTest

from frontend.api_client import AgenticMemoryApiClient, ApiCallResult

ENTRYPOINT = Path(__file__).resolve().parents[1] / "frontend" / "app.py"
_TEST_ACCESS_CODE = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
_TEST_ACCESS_HASH = hashlib.sha256(_TEST_ACCESS_CODE.encode("utf-8")).hexdigest()


def _configured_app() -> AppTest:
    app = AppTest.from_file(str(ENTRYPOINT))
    app.secrets["JUDGE_ACCESS_CODE_SHA256"] = _TEST_ACCESS_HASH
    return app.run()


def _widget(items, label: str):
    return next(item for item in items if item.label == label)


def _unlock(app: AppTest) -> None:
    _widget(app.text_input, "Judge access code").input(_TEST_ACCESS_CODE)
    _widget(app.button, "Unlock Live Investigation").click().run()


def test_app_loads_with_expected_sections() -> None:
    app = _configured_app()

    assert "Agentic Incident Command Center" in [item.value for item in app.title]
    assert "Investigate an active incident" in [item.value for item in app.subheader]
    assert _widget(app.button, "⚡ Run Agentic Investigation").disabled is True
    assert not app.exception


def test_judge_tip_is_visible_before_investigation() -> None:
    app = _configured_app()

    markdown = "\n".join(item.value for item in app.markdown)
    assert "Judge tip:" in markdown
    assert "Custom incident" in markdown
    assert "Privacy Guard" in markdown


def test_missing_access_secret_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("JUDGE_ACCESS_CODE_SHA256", raising=False)
    app = AppTest.from_file(str(ENTRYPOINT)).run()

    assert _widget(app.button, "⚡ Run Agentic Investigation").disabled is True
    assert any("not configured" in item.value for item in app.warning)
    assert not app.exception


def test_malformed_access_secret_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("JUDGE_ACCESS_CODE_SHA256", raising=False)
    app = AppTest.from_file(str(ENTRYPOINT))
    app.secrets["JUDGE_ACCESS_CODE_SHA256"] = "not-a-sha256-digest"
    app = app.run()

    assert _widget(app.button, "⚡ Run Agentic Investigation").disabled is True
    assert any("not configured" in item.value for item in app.warning)
    assert not app.exception


def test_short_pin_is_rejected_even_if_its_hash_matches(monkeypatch) -> None:
    monkeypatch.delenv("JUDGE_ACCESS_CODE_SHA256", raising=False)
    short_pin = "012345"
    app = AppTest.from_file(str(ENTRYPOINT))
    app.secrets["JUDGE_ACCESS_CODE_SHA256"] = hashlib.sha256(
        short_pin.encode("utf-8")
    ).hexdigest()
    app = app.run()

    _widget(app.text_input, "Judge access code").input(short_pin)
    _widget(app.button, "Unlock Live Investigation").click().run()

    assert app.session_state["judge_live_investigation_unlocked"] is False
    assert _widget(app.button, "⚡ Run Agentic Investigation").disabled is True
    assert any("invalid" in item.value.lower() for item in app.error)
    assert not app.exception


def test_invalid_access_code_does_not_unlock() -> None:
    app = _configured_app()

    _widget(app.text_input, "Judge access code").input("x" * 32)
    _widget(app.button, "Unlock Live Investigation").click().run()

    assert app.session_state["judge_live_investigation_unlocked"] is False
    assert _widget(app.button, "⚡ Run Agentic Investigation").disabled is True
    assert any("invalid" in item.value.lower() for item in app.error)
    assert not app.exception


def test_access_code_unlocks_for_current_session_only() -> None:
    app = _configured_app()
    _unlock(app)

    assert app.session_state["judge_live_investigation_unlocked"] is True
    assert _widget(app.button, "⚡ Run Agentic Investigation").disabled is False
    assert not any(item.label == "Judge access code" for item in app.text_input)
    assert not app.exception


def test_access_code_is_not_forwarded_to_analysis_payload(monkeypatch) -> None:
    calls: list[dict[str, str]] = []
    monkeypatch.setenv(
        "AGENTIC_MEMORY_API_ENDPOINT",
        "https://example.test/v1/servicenow/analyze",
    )
    monkeypatch.setenv("AGENTIC_MEMORY_API_KEY", "synthetic-test-key")

    def analyze(_client, payload):
        calls.append(payload)
        return ApiCallResult(
            payload={
                "recommendation": "Inspect the validated synthetic evidence.",
                "supporting_incident_ids": [],
                "supporting_incidents": [],
            },
            round_trip_ms=25.0,
            transient_retry_occurred=False,
        )

    monkeypatch.setattr(AgenticMemoryApiClient, "analyze", analyze)
    app = _configured_app()

    _unlock(app)

    assert _widget(app.button, "⚡ Run Agentic Investigation").disabled is False
    assert app.session_state["judge_live_investigation_unlocked"] is True
    assert not any(item.label == "Judge access code" for item in app.text_input)

    _widget(app.button, "⚡ Run Agentic Investigation").click().run()

    assert len(calls) == 1
    assert "Judge access code" not in str(calls[0])
    assert "JUDGE_ACCESS_CODE_SHA256" not in str(calls[0])
    headings = [item.value for item in app.subheader]
    assert "Agentic Memory Trace" in headings
    assert "Recommendation" in headings
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
    app = _configured_app()

    assert "What just happened?" not in [item.value for item in app.subheader]
    _unlock(app)
    _widget(app.button, "⚡ Run Agentic Investigation").click().run()

    headings = [item.value for item in app.subheader]
    assert "Agentic Memory Trace" in headings
    assert headings.index("Agentic Memory Trace") < headings.index("Recommendation")
    assert headings.index("Recommendation") < headings.index("What just happened?")
    assert headings.index("What just happened?") < headings.index(
        "Operational Memory Graph"
    )
    assert "Verified Security Controls" in headings
    assert not app.exception
