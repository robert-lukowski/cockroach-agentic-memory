"""Tests for pure operational-memory graph construction."""

from frontend.graph import build_operational_memory_graph
from frontend.models import AnalysisResult, SupportingIncident


def _supporting_incident(index: int, similarity: float | None) -> SupportingIncident:
    return SupportingIncident(
        incident_id=f"{index:08x}-1111-4111-8111-111111111111",
        incident_number=f"INC{9_000_000 + index}",
        service=f"demo-service-{index}",
        similarity=similarity,
        root_cause=f"Synthetic root cause {index}",
        resolution=f"Synthetic resolution {index}",
    )


def _result(
    supporting: tuple[SupportingIncident, ...] = (),
    legacy_ids: tuple[str, ...] = (),
) -> AnalysisResult:
    return AnalysisResult(
        recommendation="Inspect the retrieved operational memory.",
        confidence=0.87,
        timings={},
        supporting_incidents=supporting,
        legacy_incident_ids=legacy_ids,
    )


def test_rich_graph_is_a_star_with_one_current_node() -> None:
    incidents = tuple(_supporting_incident(index, 0.95 - index / 20) for index in range(1, 6))

    graph = build_operational_memory_graph(
        _result(incidents),
        current_incident_number="INC9000030",
        current_service="current-demo-service",
    )

    assert graph.state == "rich"
    assert len(graph.nodes) == 6
    assert sum(node.is_current for node in graph.nodes) == 1
    assert len(graph.edges) == 5
    assert {edge.source_id for edge in graph.edges} == {"current-incident"}
    assert {edge.target_id for edge in graph.edges} == {
        "historical-1",
        "historical-2",
        "historical-3",
        "historical-4",
        "historical-5",
    }


def test_incident_number_is_preferred_and_similarity_is_preserved() -> None:
    incident = SupportingIncident(
        incident_id="11111111-1111-4111-8111-111111111111",
        incident_number="INC9000016",
        service="outbound-orchestrator",
        similarity=0.82,
        root_cause="Synthetic concurrency exhaustion.",
        resolution="Synthetic concurrency allocation correction.",
    )

    graph = build_operational_memory_graph(
        _result((incident,)),
        current_incident_number="INC9000003",
        current_service="connect-outbound-orchestrator",
    )

    current, historical = graph.nodes
    assert current.label == (
        "INC9000003\nCurrent Incident\nconnect-outbound-orchestrator"
    )
    assert historical.label == "INC9000016\noutbound-orchestrator"
    assert incident.incident_id not in historical.label
    assert historical.similarity == 0.82
    assert graph.edges[0].similarity == 0.82


def test_current_node_is_clearly_marked_without_duplicating_its_fallback() -> None:
    graph = build_operational_memory_graph(
        _result((_supporting_incident(1, None),)),
        current_incident_number=" ",
        current_service="connect-outbound-orchestrator",
    )

    assert graph.nodes[0].label == "Current Incident\nconnect-outbound-orchestrator"
    assert graph.nodes[0].label.count("Current Incident") == 1
    assert graph.nodes[0].identifier == ""
    assert graph.edges[0].similarity is None


def test_missing_or_unknown_historical_service_is_omitted_from_node_label() -> None:
    incident = _supporting_incident(1, 0.75)
    for service in ("unknown", "", "  "):
        incomplete_incident = SupportingIncident(
            incident_id=incident.incident_id,
            incident_number=incident.incident_number,
            service=service,
            similarity=incident.similarity,
            root_cause=incident.root_cause,
            resolution=incident.resolution,
        )

        graph = build_operational_memory_graph(
            _result((incomplete_incident,)),
            current_incident_number="INC9000030",
            current_service="current-service",
        )

        assert graph.nodes[1].label == "INC9000001"


def test_empty_result_has_no_invented_nodes_or_edges() -> None:
    graph = build_operational_memory_graph(
        _result(),
        current_incident_number="INC9000030",
        current_service="demo-service",
    )

    assert graph.state == "empty"
    assert graph.nodes == ()
    assert graph.edges == ()


def test_legacy_result_remains_a_non_graph_fallback() -> None:
    graph = build_operational_memory_graph(
        _result(legacy_ids=("11111111-1111-4111-8111-111111111111",)),
        current_incident_number="INC9000030",
        current_service="demo-service",
    )

    assert graph.state == "legacy"
    assert graph.nodes == ()
    assert graph.edges == ()
