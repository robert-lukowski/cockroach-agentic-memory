"""Focused tests for frontend rendering behavior."""

from contextlib import nullcontext

from frontend import ui_components
from frontend.graph import build_operational_memory_graph
from frontend.models import AnalysisResult, SupportingIncident


def _result(
    *, recommendation: str = "Diagnosis\n1. Inspect the synthetic service."
) -> AnalysisResult:
    return AnalysisResult(
        recommendation=recommendation,
        confidence=0.8,
        timings={
            "vector_retrieval_ms": 120.0,
            "bedrock_inference_ms": 800.0,
            "total_request_ms": 1_000.0,
        },
        supporting_incidents=(),
        legacy_incident_ids=(),
    )


def test_recommendation_is_rendered_in_full(monkeypatch) -> None:
    recommendation = "Diagnosis\n" + "\n".join(
        f"{index}. Complete synthetic action {index}." for index in range(1, 41)
    )
    rendered: list[str] = []
    monkeypatch.setattr(ui_components.st, "subheader", lambda _label: None)
    monkeypatch.setattr(ui_components.st, "text", rendered.append)

    ui_components.render_recommendation(_result(recommendation=recommendation))

    assert rendered == [recommendation]


def test_client_round_trip_is_rendered_once_and_not_mixed_with_backend_timings(
    monkeypatch,
) -> None:
    metric_calls: list[tuple[str, str]] = []
    timing_lines: list[str] = []
    captions: list[str] = []

    class MetricColumn:
        def metric(self, label: str, value: str) -> None:
            metric_calls.append((label, value))

    monkeypatch.setattr(ui_components.st, "columns", lambda _count: [MetricColumn()] * 4)
    monkeypatch.setattr(ui_components.st, "expander", lambda _label: nullcontext())
    monkeypatch.setattr(ui_components.st, "write", timing_lines.append)
    monkeypatch.setattr(ui_components.st, "caption", captions.append)

    result = _result()
    ui_components.render_metrics(result, round_trip_ms=1_234.0)
    ui_components.render_timings(result)

    assert metric_calls[-1] == ("Client round trip", "1,234 ms")
    assert sum(label == "Client round trip" for label, _value in metric_calls) == 1
    assert timing_lines == [
        "Vector retrieval: 120 ms",
        "Bedrock inference: 800 ms",
        "Total request: 1,000 ms",
    ]
    assert captions == []


def test_plotly_figure_uses_similarity_and_escapes_hover_text() -> None:
    incident = SupportingIncident(
        incident_id="11111111-1111-4111-8111-111111111111",
        incident_number="INC9000016",
        service="synthetic <service>",
        similarity=0.8,
        root_cause="Synthetic <root cause>",
        resolution="Synthetic resolution.",
    )
    result = AnalysisResult(
        recommendation="Inspect the retrieved operational memory.",
        confidence=None,
        timings={},
        supporting_incidents=(incident,),
        legacy_incident_ids=(),
    )
    graph = build_operational_memory_graph(
        result,
        current_incident_number="INC9000030",
        current_service="current-service",
    )

    figure = ui_components.build_operational_memory_figure(graph)

    assert len(figure.data) == 3
    assert abs(figure.data[0].line.width - 4.3) < 1e-9
    assert [trace.name for trace in figure.data[1:]] == [
        "Current Incident",
        "Resolved Memory",
    ]
    assert all(trace.showlegend for trace in figure.data[1:])
    assert figure.data[1].text[0] == (
        "INC9000030<br>Current Incident<br>current-service"
    )
    assert figure.data[2].text[0] == "INC9000016<br>synthetic &lt;service&gt;"
    historical_hover = figure.data[2].hovertext[0]
    assert "synthetic &lt;service&gt;" in historical_hover
    assert "Synthetic &lt;root cause&gt;" in historical_hover
    assert "synthetic <service>" not in historical_hover


def test_current_incident_hover_contains_only_current_data() -> None:
    incident = SupportingIncident(
        incident_id="11111111-1111-4111-8111-111111111111",
        incident_number="INC9000016",
        service="historical-service",
        similarity=0.8,
        root_cause="Historical root cause.",
        resolution="Historical resolution.",
    )
    result = AnalysisResult(
        recommendation="Inspect the retrieved operational memory.",
        confidence=None,
        timings={},
        supporting_incidents=(incident,),
        legacy_incident_ids=(),
    )
    graph = build_operational_memory_graph(
        result,
        current_incident_number="INC9000030",
        current_service="current-service",
    )

    figure = ui_components.build_operational_memory_figure(graph)

    current_hover = figure.data[1].hovertext[0]
    assert "Current Incident" in current_hover
    assert "INC9000030" in current_hover
    assert "current-service" in current_hover
    assert "Semantic similarity" not in current_hover
    assert "Root cause" not in current_hover
    assert "Resolution" not in current_hover
