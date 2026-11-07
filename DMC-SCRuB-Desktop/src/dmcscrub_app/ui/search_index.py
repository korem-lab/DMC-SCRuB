"""What the Find box can look for, and how typed text becomes a diagram target.

Deliberately free of Qt, so the matching rules can be exercised without a window,
and free of node IDs: those are renumbered on every rebuild, so a target is always a
name the data itself carries. A batch's name is the one the diagram already prints on
the box, which is what lets it double as the target with nothing to parse.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from dmcscrub_app.core.workflow import SearchEntry, WorkflowGraph, WorkflowGraphNode

KIND_ROW = "row"
KIND_STEP = "step"
KIND_BATCH = "batch"
KINDS = (KIND_ROW, KIND_STEP, KIND_BATCH)

KIND_LABEL = {KIND_ROW: "sample/control", KIND_STEP: "step", KIND_BATCH: "batch"}
KIND_PLACEHOLDER = {
    KIND_ROW: "Sample or control name",
    KIND_STEP: "Step name",
    KIND_BATCH: "Batch name",
}
KIND_MISS = {
    KIND_ROW: "No sample or control matches this text.",
    KIND_STEP: "No step matches this text.",
    KIND_BATCH: "No batch matches this text.",
}

_MUTED = "#94a3b8"


@dataclass(frozen=True)
class FindItem:
    """One findable thing: `value` goes to the diagram, `html` goes on screen."""

    value: str
    html: str


class SearchIndex:
    """The three lists the Find box offers, and the matching over them."""

    def __init__(
        self,
        rows: list[FindItem] | None = None,
        steps: list[FindItem] | None = None,
        batches: list[FindItem] | None = None,
    ) -> None:
        self._items: dict[str, list[FindItem]] = {
            KIND_ROW: list(rows or []),
            KIND_STEP: list(steps or []),
            KIND_BATCH: list(batches or []),
        }
        self._exact: dict[str, dict[str, str]] = {}
        for kind, items in self._items.items():
            table: dict[str, str] = {}
            for item in items:
                # First one wins, which settles the one case where two entries share a
                # value: batch names are "step: batch", so a colon inside either half
                # can spell the same label twice.
                table.setdefault(item.value.lower(), item.value)
            self._exact[kind] = table

    @classmethod
    def from_graph(
        cls, graph: WorkflowGraph | None, rows: list[SearchEntry]
    ) -> SearchIndex:
        """Rows come from the caller; steps and batches only exist on the graph."""
        nodes = list(graph.nodes) if graph is not None else []
        columns = sorted({(node.level, node.step_column) for node in nodes})
        return cls(
            rows=[_row_item(entry) for entry in rows],
            steps=[FindItem(column, html.escape(column)) for _, column in columns],
            batches=[
                _batch_item(node)
                for node in sorted(nodes, key=lambda node: (node.level, node.name))
            ],
        )

    def matches(self, kind: str, text: str) -> list[FindItem]:
        """Every entry of this kind containing `text`.

        Matching runs over the whole value, so typing a batch name finds the
        "step: batch" entry that holds it and typing a step name lists its batches.
        """
        needle = text.strip().lower()
        if not needle:
            return []
        return [item for item in self._items[kind] if needle in item.value.lower()]

    def resolve(self, kind: str, text: str) -> str | None:
        """The one target this text names exactly, or None if it names none."""
        return self._exact[kind].get(text.strip().lower())


def _row_item(entry: SearchEntry) -> FindItem:
    label = html.escape(entry.entry_id)
    if entry.is_control:
        label += f" <span style='color:{_MUTED}'>\u00b7 control</span>"
    return FindItem(entry.entry_id, label)


def _batch_item(node: WorkflowGraphNode) -> FindItem:
    # Bold on the batch alone, which is what keeps the split readable when either half
    # of "step: batch" carries a colon of its own.
    return FindItem(
        node.name,
        f"{html.escape(node.step_column)}: <b>{html.escape(node.batch_value)}</b>",
    )
