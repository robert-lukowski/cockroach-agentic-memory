"""Pure operational-memory graph data generation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from frontend.models import AnalysisResult

GraphState = Literal["rich", "legacy", "empty"]


@dataclass(frozen=True, slots=True)
class GraphNode:
    node_id: str
    label: str
    service: str
    x: float
    y: float
    is_current: bool
    similarity: float | None = None
    root_cause: str = ""
    resolution: str = ""


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source_id: str
    target_id: str
    similarity: float | None


@dataclass(frozen=True, slots=True)
class OperationalMemoryGraph:
    state: GraphState
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


def build_operational_memory_graph(
    result: AnalysisResult,
    *,
    current_incident_number: str,
    current_service: str,
) -> OperationalMemoryGraph:
    """Build a star topology containing only API-retrieved historical evidence."""
    if not result.supporting_incidents:
        state: GraphState = "legacy" if result.legacy_incident_ids else "empty"
        return OperationalMemoryGraph(state=state, nodes=(), edges=())

    current_id = "current-incident"
    current_label = current_incident_number.strip() or "Current Incident"
    current_node = GraphNode(
        node_id=current_id,
        label=current_label,
        service=current_service.strip() or "unknown",
        x=0.0,
        y=0.0,
        is_current=True,
    )
    historical_nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    count = len(result.supporting_incidents)
    for index, incident in enumerate(result.supporting_incidents):
        angle = (math.pi / 2) - (2 * math.pi * index / count)
        node_id = f"historical-{index + 1}"
        historical_nodes.append(
            GraphNode(
                node_id=node_id,
                label=incident.display_identifier,
                service=incident.service,
                x=math.cos(angle),
                y=math.sin(angle),
                is_current=False,
                similarity=incident.similarity,
                root_cause=incident.root_cause,
                resolution=incident.resolution,
            )
        )
        edges.append(
            GraphEdge(
                source_id=current_id,
                target_id=node_id,
                similarity=incident.similarity,
            )
        )
    return OperationalMemoryGraph(
        state="rich",
        nodes=(current_node, *historical_nodes),
        edges=tuple(edges),
    )
