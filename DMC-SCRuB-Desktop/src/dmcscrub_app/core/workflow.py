from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from dmcscrub_app.core.models import InputData
from dmcscrub_app.core.validation import parse_is_control


@dataclass(frozen=True)
class WorkflowStepConfig:
    column: str
    enabled: bool = True
    control_groups: list[str] = field(default_factory=list)
    run_decontamination: bool = True


@dataclass(frozen=True)
class WorkflowGraphNode:
    node_id: str
    name: str
    step_column: str
    batch_value: str
    sample_ids: list[str]
    level: int
    parents: list[str] = field(default_factory=list)
    control_groups: list[str] = field(default_factory=list)
    control_ids: list[str] = field(default_factory=list)
    # Controls this step does not draw on, but which are in this batch all the same:
    # usually collected by an earlier step, though a control no step selected lands
    # here too, as does one whose own step comes later. Shown in the diagram,
    # deliberately absent from `sample_ids` so that edges, search and highlighting
    # keep their meaning.
    prior_control_ids: list[str] = field(default_factory=list)
    run_decontamination: bool = True


@dataclass(frozen=True)
class WorkflowGraphEdge:
    edge_id: str
    parent_id: str
    child_id: str
    sample_ids: list[str]
    # Controls that travel this link as well. A link with controls but no samples is one
    # a control took on its own, which the diagram draws faintly.
    control_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowGraph:
    steps: list[WorkflowStepConfig]
    nodes: list[WorkflowGraphNode]
    edges: list[WorkflowGraphEdge]
    system_edges: list[tuple[str, str]]


@dataclass(frozen=True)
class SearchEntry:
    """One searchable ID for the diagram's sample search."""

    entry_id: str
    is_control: bool


def search_entries(input_data: InputData) -> list[SearchEntry]:
    metadata = input_data.metadata.loc[input_data.counts.index]
    is_control = parse_is_control(metadata["is_control"])
    entries = [
        SearchEntry(entry_id=str(sample_id), is_control=bool(flag))
        for sample_id, flag in zip(metadata.index, is_control)
    ]
    return sorted(entries, key=lambda entry: entry.entry_id)


def search_entries_from_graph(graph: WorkflowGraph) -> list[SearchEntry]:
    """All the diagram knows about, for pages that have no count table to read."""
    samples: set[str] = set()
    controls: set[str] = set()
    for node in graph.nodes:
        samples.update(node.sample_ids)
        controls.update(node.control_ids)
        controls.update(node.prior_control_ids)
    entries = [SearchEntry(entry_id=item, is_control=False) for item in samples]
    entries.extend(SearchEntry(entry_id=item, is_control=True) for item in controls - samples)
    return sorted(entries, key=lambda entry: entry.entry_id)


def build_workflow_graph(input_data: InputData, steps: list[WorkflowStepConfig]) -> WorkflowGraph:
    metadata = input_data.metadata.loc[input_data.counts.index].copy()
    enabled_steps = [step for step in steps if step.enabled]
    is_control = parse_is_control(metadata["is_control"])
    control_groups = metadata["Groups"].astype(str).str.strip()

    nodes: list[WorkflowGraphNode] = []
    node_samples: dict[str, set[str]] = {}
    node_controls: dict[str, set[str]] = {}
    nodes_by_step: dict[str, list[str]] = {}
    next_index = 1

    for level, step in enumerate(enabled_steps, start=1):
        eligible_mask = ~is_control
        # Same rule the backend uses to fill a source: a control belongs to this batch
        # only if the step selected its group. Controls without a batch value belong
        # nowhere here, since "step-wide or skip" is only decided at pre-flight time.
        selected_controls = is_control & control_groups.isin(list(step.control_groups))
        raw_values = metadata[step.column]
        valid_values = raw_values.notna() & raw_values.astype(str).str.strip().ne("")
        values = raw_values.where(valid_values, pd.NA).astype("string").str.strip()
        batch_values = sorted(value for value in values.dropna().unique().tolist() if value)
        nodes_by_step[step.column] = []
        for batch_value in batch_values:
            in_batch = values == batch_value
            # A batch of nothing but controls still gets a node: pooling several
            # batches' blanks onto one plate is ordinary, and that plate is where a
            # control's journey continues.
            sample_ids = metadata.index[eligible_mask & in_batch].astype(str).tolist()
            control_ids = metadata.index[selected_controls & in_batch].astype(str).tolist()
            prior_control_ids = (
                metadata.index[is_control & ~selected_controls & in_batch].astype(str).tolist()
            )
            node_id = f"S{next_index}"
            next_index += 1
            node_samples[node_id] = set(sample_ids)
            node_controls[node_id] = set(control_ids) | set(prior_control_ids)
            nodes_by_step[step.column].append(node_id)
            nodes.append(
                WorkflowGraphNode(
                    node_id=node_id,
                    name=f"{step.column}: {batch_value}",
                    step_column=step.column,
                    batch_value=batch_value,
                    sample_ids=sample_ids,
                    level=level,
                    control_groups=list(step.control_groups),
                    control_ids=control_ids,
                    prior_control_ids=prior_control_ids,
                    run_decontamination=step.run_decontamination,
                )
            )

    # Two batches are linked by any row they share. Samples draw the workflow's main
    # lanes; a control collected in an earlier step and re-run here links its two
    # batches on its own, even when no sample takes that route.
    parents_by_node: dict[str, set[str]] = {node.node_id: set() for node in nodes}
    shared_rows: dict[tuple[str, str], tuple[list[str], list[str]]] = {}
    for left, right in zip(enabled_steps, enabled_steps[1:]):
        for parent_id in nodes_by_step.get(left.column, []):
            for child_id in nodes_by_step.get(right.column, []):
                samples = sorted(node_samples[parent_id] & node_samples[child_id])
                controls = sorted(node_controls[parent_id] & node_controls[child_id])
                if not samples and not controls:
                    continue
                parents_by_node[child_id].add(parent_id)
                shared_rows[(parent_id, child_id)] = (samples, controls)

    nodes = [
        WorkflowGraphNode(
            node_id=node.node_id,
            name=node.name,
            step_column=node.step_column,
            batch_value=node.batch_value,
            sample_ids=node.sample_ids,
            level=node.level,
            parents=sorted(parents_by_node[node.node_id]),
            control_groups=node.control_groups,
            control_ids=node.control_ids,
            prior_control_ids=node.prior_control_ids,
            run_decontamination=node.run_decontamination,
        )
        for node in nodes
    ]

    parent_ids = {parent for node in nodes for parent in node.parents}
    child_ids = {node.node_id for node in nodes if node.parents}
    root_ids = [node.node_id for node in nodes if node.node_id not in child_ids]
    leaf_ids = [node.node_id for node in nodes if node.node_id not in parent_ids]
    system_edges = [(node_id, "END") for node_id in leaf_ids]

    nodes_by_id = {node.node_id: node for node in nodes}
    edges: list[WorkflowGraphEdge] = []
    for node_id in root_ids:
        node = nodes_by_id[node_id]
        edges.append(
            WorkflowGraphEdge(
                edge_id=f"INI__{node.node_id}",
                parent_id="INI",
                child_id=node.node_id,
                sample_ids=list(node.sample_ids),
                control_ids=sorted(node_controls[node.node_id]),
            )
        )
    for child in nodes:
        for parent_id in child.parents:
            samples, controls = shared_rows[(parent_id, child.node_id)]
            edges.append(
                WorkflowGraphEdge(
                    edge_id=f"{parent_id}__{child.node_id}",
                    parent_id=parent_id,
                    child_id=child.node_id,
                    sample_ids=samples,
                    control_ids=controls,
                )
            )

    return WorkflowGraph(steps=enabled_steps, nodes=nodes, edges=edges, system_edges=system_edges)
