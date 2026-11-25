"""`view_snapshot.json`: the three columns as they looked when Run was clicked.

Written by the UI, not by the backend, so the backend never has to know the UI's
view models exist. The moment is deliberate: everything here is already in
`DatasetView`'s hands when the button is pressed, and the controls are locked for
the rest of the run, so there is nothing to recompute.

The left column in particular must be snapshotted rather than recomputed later.
Recomputing means re-reading the whole count table every time a history entry is
opened, and worse, the user may have moved or edited that file since -- in which
case the summary would describe data this run never saw.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dmcscrub_app.core.workflow import (
    WorkflowGraph,
    WorkflowGraphEdge,
    WorkflowGraphNode,
    WorkflowStepConfig,
)
from dmcscrub_app.ui.models import (
    ConcentrationEntry,
    InputFile,
    InputSummaryVM,
    MetricRow,
    PipelineStep,
    PipelineVM,
)

SNAPSHOT_SCHEMA_VERSION = 3


class SnapshotVersionError(ValueError):
    """Snapshot written by an incompatible version of the app."""


def build_snapshot(
    summary: InputSummaryVM,
    pipeline: PipelineVM,
    selections: list[dict[str, Any]],
    graph: WorkflowGraph,
    *,
    algorithm: str = "",
    concentrations: list[ConcentrationEntry] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "algorithm": algorithm,
        "concentrations": [
            asdict(entry) for entry in (concentrations or [])
        ],
        "summary": {
            "samples": [asdict(row) for row in summary.samples],
            "controls": [asdict(row) for row in summary.controls],
            "features": [asdict(row) for row in summary.features],
            "files": [asdict(item) for item in summary.files],
        },
        "pipeline": {
            "total_samples": pipeline.total_samples,
            "steps": [asdict(step) for step in pipeline.steps],
            "all_control_groups": list(pipeline.all_control_groups),
        },
        "selections": [dict(entry) for entry in selections],
        "graph": {
            "steps": [asdict(step) for step in graph.steps],
            "nodes": [asdict(node) for node in graph.nodes],
            "edges": [asdict(edge) for edge in graph.edges],
            "system_edges": [list(edge) for edge in graph.system_edges],
        },
    }


def write_snapshot(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    version = payload.get("schema_version")
    if version != SNAPSHOT_SCHEMA_VERSION:
        # No migration code during development: the detail page refuses to open and
        # says so, while the history row and its downloads keep working.
        raise SnapshotVersionError(
            f"This snapshot was written by another version of the app "
            f"(schema {version!r}, expected {SNAPSHOT_SCHEMA_VERSION})."
        )
    return payload


def summary_from_snapshot(payload: dict[str, Any]) -> InputSummaryVM:
    section = payload.get("summary") or {}
    return InputSummaryVM(
        samples=[MetricRow(**row) for row in section.get("samples", [])],
        controls=[MetricRow(**row) for row in section.get("controls", [])],
        features=[MetricRow(**row) for row in section.get("features", [])],
        files=[InputFile(**item) for item in section.get("files", [])],
    )


def pipeline_from_snapshot(payload: dict[str, Any]) -> PipelineVM:
    section = payload.get("pipeline") or {}
    return PipelineVM(
        total_samples=section.get("total_samples", 0),
        steps=[PipelineStep(**step) for step in section.get("steps", [])],
        all_control_groups=list(section.get("all_control_groups", [])),
    )


def graph_from_snapshot(payload: dict[str, Any]) -> WorkflowGraph:
    """Rebuilt as a real graph, not as a picture.

    Feeding this to `DagCanvas.set_graph` gives a zoomable DAG with the simplified
    mode still available, which no PNG could do.
    """
    section = payload.get("graph") or {}
    return WorkflowGraph(
        steps=[WorkflowStepConfig(**step) for step in section.get("steps", [])],
        nodes=[WorkflowGraphNode(**node) for node in section.get("nodes", [])],
        edges=[WorkflowGraphEdge(**edge) for edge in section.get("edges", [])],
        system_edges=[tuple(edge) for edge in section.get("system_edges", [])],
    )


def selections_from_snapshot(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(entry) for entry in payload.get("selections", [])]


def concentrations_from_snapshot(
    payload: dict[str, Any],
) -> list[ConcentrationEntry]:
    return [
        ConcentrationEntry(**entry)
        for entry in payload.get("concentrations", [])
    ]
