from __future__ import annotations

import html
from collections import defaultdict
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QPointF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
)

from dmcscrub_app.core.workflow import WorkflowGraph, WorkflowGraphNode
from dmcscrub_app.ui.search_index import KIND_BATCH, KIND_ROW, KIND_STEP

_MIN_ZOOM = 0.08
_MAX_ZOOM = 4.0

_BOX_W = 260.0
_BOX_H = 86.0
_X_GAP = 360.0
_Y_GAP = 140.0

_NODE_BORDER = "#94a3b8"
_NODE_FILL = "#ffffff"
_NODE_TEXT = "#172033"
_SKIP_BORDER = "#cbd5e1"
_SKIP_FILL = "#f1f5f9"
_SKIP_TEXT = "#64748b"
_SYSTEM_BORDER = "#2563eb"
_SYSTEM_FILL = "#dbeafe"
_SYSTEM_TEXT = "#102033"
_EDGE_COLOR = "#64748b"
# A link no sample takes: only a control was carried along it.
_WEAK_EDGE_COLOR = "#cbd5e1"
_SAMPLE_BORDER = "#16a34a"
_SAMPLE_FILL = "#dcfce7"
_CONTROL_BORDER = "#dc2626"
_CONTROL_FILL = "#fee2e2"
# A batch where the control is only passing through, rather than acting as its source.
_CARRIED_BORDER = "#fca5a5"
_CARRIED_FILL = "#fef2f2"
# A batch a searched-for batch's own rows travel on to.
_TOUCHED_BORDER = "#86efac"
_TOUCHED_FILL = "#f0fdf4"

# How many IDs a hover tooltip lists before it gives up and points at the click.
_TOOLTIP_LIMIT = 10

_NODE_KEY = 0


@dataclass
class _NodeDetail:
    """Everything a node can say about itself, for the tooltip and the dialog."""

    title: str
    subtitle: str
    sample_ids: list[str] = field(default_factory=list)
    control_ids: list[str] = field(default_factory=list)
    prior_control_ids: list[str] = field(default_factory=list)

    @property
    def sample_total(self) -> int:
        """Samples, plus the controls only passing through this batch."""
        return len(self.sample_ids) + len(self.prior_control_ids)


@dataclass(frozen=True)
class _Shades:
    """The strong/weak pair of box colours one kind of search paints with."""

    strong_border: str
    strong_fill: str
    weak_border: str
    weak_fill: str


_GREEN = _Shades(_SAMPLE_BORDER, _SAMPLE_FILL, _TOUCHED_BORDER, _TOUCHED_FILL)
_RED = _Shades(_CONTROL_BORDER, _CONTROL_FILL, _CARRIED_BORDER, _CARRIED_FILL)


@dataclass
class _Highlight:
    """Which boxes and arrows one search lights up, in two shades.

    `strong` is what was asked for and `weak` is where it also turns up: a control's
    own step against the batches it is merely carried through, or a batch itself
    against the batches its rows travel on to. The arrows take the colour of whatever
    travels them, so a searched row paints its own route strongly while a batch's
    spreading contents only tint the routes they take.
    """

    strong: list[str] = field(default_factory=list)
    weak: list[str] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)
    shades: _Shades = _GREEN
    edge_color: str = _SAMPLE_BORDER

    @property
    def hits(self) -> int:
        return len(self.strong) + len(self.weak)


class _NodeItem(QGraphicsRectItem):
    """A node box that shows its summary the moment the pointer arrives.

    Qt's own item tooltips work here, but only after the roughly one-second rest
    that `QApplication` insists on, which reads as "hovering does nothing". Driving
    `QToolTip` from the hover events makes it immediate. Hover is independent of
    the mouse buttons, so dragging the canvas is unaffected.
    """

    def __init__(self, x: float, y: float, width: float, height: float, tip: str) -> None:
        super().__init__(x, y, width, height)
        self._tip = tip
        self.setToolTip(tip)
        self.setAcceptHoverEvents(True)

    def hoverEnterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        QToolTip.showText(event.screenPos(), self._tip, event.widget())
        super().hoverEnterEvent(event)

    def hoverMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Only once it has timed out, so the tip doesn't chase the pointer around.
        if not QToolTip.isVisible():
            QToolTip.showText(event.screenPos(), self._tip, event.widget())
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        QToolTip.hideText()
        super().hoverLeaveEvent(event)


class _DagView(QGraphicsView):
    """A view where a left-click on a node opens it but a drag still pans."""

    node_clicked = Signal(str)
    zoom_requested = Signal(float)

    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self._press_pos = None

    def viewportEvent(self, event) -> bool:  # noqa: N802 (Qt override)
        # Trackpad pinch. macOS reports it as a native gesture rather than as a
        # wheel, and each event carries an incremental scale rather than a total.
        if event.type() == QEvent.NativeGesture and event.gestureType() == Qt.ZoomNativeGesture:
            self.zoom_requested.emit(1.0 + event.value())
            return True
        return super().viewportEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # The desktop convention everywhere pinch is unavailable; plain scrolling
        # stays scrolling.
        if event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier):
            delta = event.angleDelta().y()
            if delta:
                self.zoom_requested.emit(1.0015**delta)
                event.accept()
                return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        press = self._press_pos
        self._press_pos = None
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton or press is None:
            return
        # Anything but the smallest movement was the user panning the canvas, and
        # panning should never pop a dialog open when the drag happens to end on a node.
        if (event.position().toPoint() - press).manhattanLength() > 4:
            return
        key = self._key_at(press)
        if key:
            self.node_clicked.emit(key)

    def _key_at(self, point) -> str:
        item = self.itemAt(point)
        while item is not None:
            key = item.data(_NODE_KEY)
            if key:
                return str(key)
            item = item.parentItem()
        return ""


class NodeDetailsDialog(QDialog):
    """The full membership of one node, which the tooltip only summarises."""

    def __init__(self, detail: _NodeDetail, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(detail.title)
        self.setMinimumSize(420, 380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        heading = QLabel(detail.title)
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)

        subtitle = QLabel(detail.subtitle)
        subtitle.setObjectName("metricLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addWidget(self._section("Samples", detail.sample_ids), 1)
        layout.addWidget(self._section("Controls", detail.control_ids), 1)
        layout.addWidget(
            self._section("Controls from previous step", detail.prior_control_ids), 1
        )

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _section(self, title: str, ids: list[str]) -> QFrame:
        frame = QFrame()
        box = QVBoxLayout(frame)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        header = QLabel(f"{title} ({len(ids)})")
        header.setObjectName("summaryCardTitle")
        box.addWidget(header)
        listing = QListWidget()
        listing.addItems(ids or ["none"])
        listing.setSelectionMode(QListWidget.ExtendedSelection)
        listing.setCurrentRow(-1)
        box.addWidget(listing)
        return frame


class DagCanvas(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("dagFrame")
        self.scene = QGraphicsScene(self)
        self.view = _DagView(self.scene)
        self.view.setObjectName("dagView")
        self.zoom_factor = 1.0
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.view.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        # A floor, not a preference: the splitter's stretch factor is what makes the
        # diagram tall, so this only needs to stay above "unusable" for the case where
        # the Result card appears below and takes a share of the column.
        self.view.setMinimumHeight(180)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.node_clicked.connect(self._show_node_details)
        self.view.zoom_requested.connect(self.zoom)

        title = QLabel("Workflow Diagram")
        title.setObjectName("panelTitle")
        title.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
        title.setMinimumWidth(120)

        self._update_status = QLabel("Pending update\u2026")
        self._update_status.setObjectName("metricLabel")
        self._update_status.hide()

        self._graph: WorkflowGraph | None = None
        self._simplified = False
        self._view_states: dict[bool, tuple[QTransform, float, int, int]] = {}
        self._node_items: dict[str, QGraphicsItem] = {}
        self._node_texts: dict[str, QGraphicsItem] = {}
        self._node_details: dict[str, _NodeDetail] = {}
        self._edge_items: dict[tuple[str, str], list[QGraphicsItem]] = {}
        self._highlight: tuple[str, str] = (KIND_ROW, "")
        self._highlight_hits = 0
        self._node_rows: dict[str, frozenset[str]] | None = None
        self._edge_rows: dict[tuple[str, str], frozenset[str]] | None = None

        self.zoom_out_button = QPushButton("\u2212")
        self.zoom_in_button = QPushButton("+")
        self.fit_button = QPushButton("Fit the Graph")
        self.simplify_button = QPushButton("Simplify Graph")
        self.simplify_button.setCheckable(True)
        for button in (self.zoom_out_button, self.zoom_in_button):
            button.setObjectName("iconButton")
            button.setFixedWidth(28)
        for button in (self.fit_button, self.simplify_button):
            button.setObjectName("dagToolbarButton")
        self.zoom_out_button.clicked.connect(lambda: self.zoom(0.8))
        self.zoom_in_button.clicked.connect(lambda: self.zoom(1.25))
        self.fit_button.clicked.connect(self.fit_graph)
        self.simplify_button.toggled.connect(self._on_simplify_toggled)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        toolbar.addWidget(title, 1)
        toolbar.addWidget(self._update_status)
        toolbar.addWidget(self.zoom_out_button)
        toolbar.addWidget(self.zoom_in_button)
        toolbar.addWidget(self.fit_button)
        toolbar.addWidget(self.simplify_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        layout.addLayout(toolbar)
        layout.addWidget(self.view)
        self.clear()

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        # Keep the card freely shrinkable so the splitter squeezes the DAG (this
        # column) instead of cascading the resize into the side panels.
        hint = super().minimumSizeHint()
        return QSize(200, hint.height())

    def clear(self) -> None:
        self._graph = None
        self._highlight = (KIND_ROW, "")
        self._highlight_hits = 0
        self._forget_membership()
        self._forget_items()
        self.scene.clear()
        self.reset_zoom()
        self.scene.addText("Generate a workflow DAG to preview step and batch order.")

    def set_graph(self, graph: WorkflowGraph, preserve_view: bool = False) -> None:
        self._graph = graph
        self._forget_membership()
        self._render(preserve_view=preserve_view)

    def set_update_pending(self, pending: bool) -> None:
        self._update_status.setVisible(pending)

    def highlight(self, kind: str = KIND_ROW, value: str | None = None) -> int:
        """Colour what a search found: a row's route, a step's column, a batch's reach.

        The name is what gets remembered, never the node IDs it resolves to: node IDs
        are renumbered on every rebuild, so a stored one would drift onto somebody
        else's box the moment the right-hand panel changes. A batch is named by the
        label the diagram already prints on it, so there is nothing to parse.

        Called with no arguments it clears. Returns how many nodes ended up
        highlighted, so the caller can say when a name is real but absent here.
        """
        self._highlight = (kind, value or "")
        if self._graph is None:
            self._highlight_hits = 0
            return 0
        self._render(preserve_view=True)
        return self._highlight_hits

    def _on_simplify_toggled(self, checked: bool) -> None:
        if self._graph is not None:
            self._view_states[self._simplified] = self._capture_view_state()
        self._simplified = checked
        self.simplify_button.setText("Show Batches" if checked else "Simplify Graph")
        if self._graph is not None:
            self._render()
            state = self._view_states.get(checked)
            if state is not None:
                self._restore_view_state(state)
            elif checked:
                self.fit_graph()
                self._view_states[checked] = self._capture_view_state()

    def _capture_view_state(self) -> tuple[QTransform, float, int, int]:
        return (
            self.view.transform(),
            self.zoom_factor,
            self.view.horizontalScrollBar().value(),
            self.view.verticalScrollBar().value(),
        )

    def _restore_view_state(self, state: tuple[QTransform, float, int, int]) -> None:
        transform, zoom, horizontal, vertical = state
        self.view.setTransform(transform)
        self.zoom_factor = zoom
        self.view.horizontalScrollBar().setValue(horizontal)
        self.view.verticalScrollBar().setValue(vertical)

    def _forget_items(self) -> None:
        self._node_items.clear()
        self._node_texts.clear()
        self._node_details.clear()
        self._edge_items.clear()

    def _render(self, preserve_view: bool = False) -> None:
        # Snapshot the current pan/zoom so tweaks on the right panel (or toggling
        # Simplify) don't yank the canvas back to the default framing.
        prev_transform = self.view.transform()
        prev_zoom = self.zoom_factor
        prev_h = self.view.horizontalScrollBar().value()
        prev_v = self.view.verticalScrollBar().value()

        graph = self._graph
        if graph is None or not graph.nodes:
            self.clear()
            return

        self._forget_items()
        self.scene.clear()
        if self._simplified:
            positions = self._draw_simplified(graph)
        else:
            positions = self._draw_detailed(graph)
        self._apply_highlight(graph)

        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40))

        if preserve_view:
            self.view.setTransform(prev_transform)
            self.zoom_factor = prev_zoom
            self.view.horizontalScrollBar().setValue(prev_h)
            self.view.verticalScrollBar().setValue(prev_v)
        else:
            self.reset_zoom()
            self.zoom(0.8)
            self.zoom(0.8)
            self.view.centerOn(positions["INI"])

    def _draw_detailed(self, graph: WorkflowGraph) -> dict[str, QPointF]:
        positions = self._layout_positions(graph)

        nodes_by_id = {node.node_id: node for node in graph.nodes}
        edges = [(edge.parent_id, edge.child_id, not edge.sample_ids) for edge in graph.edges]
        # An arrow into END carries whatever its batch holds, so it is weak exactly when
        # that batch has no samples of its own.
        edges.extend(
            (leaf, end, not nodes_by_id[leaf].sample_ids)
            for leaf, end in graph.system_edges
            if leaf in nodes_by_id
        )
        for parent, child, weak in edges:
            if parent in positions and child in positions:
                self._draw_edge(parent, child, positions[parent], positions[child], weak=weak)

        self._draw_system_node("INI", positions["INI"])
        for node in graph.nodes:
            self._draw_node(node, positions[node.node_id])
        self._draw_system_node("END", positions["END"])
        return positions

    def _draw_simplified(self, graph: WorkflowGraph) -> dict[str, QPointF]:
        """Collapse each step into a single node (INI -> step -> ... -> END)."""
        by_level: dict[int, list[WorkflowGraphNode]] = defaultdict(list)
        for node in graph.nodes:
            by_level[node.level].append(node)
        levels = sorted(by_level)

        y = 70.0
        positions: dict[str, QPointF] = {"INI": QPointF(20.0, y)}
        step_ids: list[tuple[str, int]] = []
        for column, level in enumerate(levels):
            step_id = step_key(level)
            positions[step_id] = QPointF(420.0 + column * _X_GAP, y)
            step_ids.append((step_id, level))
        positions["END"] = QPointF(420.0 + len(levels) * _X_GAP, y)

        samples_at = {
            level: {item for node in by_level[level] for item in node.sample_ids}
            for level in levels
        }
        chain = ["INI"] + [step_id for step_id, _ in step_ids] + ["END"]
        # Which samples make each crossing: into the first step, between two steps, and
        # out of the last. An empty crossing means only controls travel it.
        crossings = [samples_at[levels[0]]]
        crossings.extend(
            samples_at[left] & samples_at[right] for left, right in zip(levels, levels[1:])
        )
        crossings.append(samples_at[levels[-1]])
        for (parent, child), rows in zip(zip(chain, chain[1:]), crossings):
            self._draw_edge(parent, child, positions[parent], positions[child], weak=not rows)

        self._draw_system_node("INI", positions["INI"])
        for step_id, level in step_ids:
            self._draw_step_summary(step_id, positions[step_id], graph, level, by_level[level])
        self._draw_system_node("END", positions["END"])
        return positions

    def _step_name(self, graph: WorkflowGraph, level: int, step_nodes: list[WorkflowGraphNode]) -> str:
        if 0 <= level - 1 < len(graph.steps):
            column = graph.steps[level - 1].column
        else:
            column = step_nodes[0].step_column
        return str(column).replace("_", " ").strip().title()

    def _step_control_groups(
        self, graph: WorkflowGraph, level: int, step_nodes: list[WorkflowGraphNode]
    ) -> list[str]:
        if 0 <= level - 1 < len(graph.steps):
            groups = graph.steps[level - 1].control_groups
        else:
            groups = step_nodes[0].control_groups
        return list(groups)

    def zoom(self, factor: float) -> None:
        # Clamped rather than refused: a pinch arrives as a stream of small factors,
        # and dropping the ones that overshoot would make it stick short of the limit.
        target = max(_MIN_ZOOM, min(_MAX_ZOOM, self.zoom_factor * factor))
        if abs(target - self.zoom_factor) < 1e-9:
            return
        applied = target / self.zoom_factor
        self.zoom_factor = target
        self.view.scale(applied, applied)

    def reset_zoom(self) -> None:
        self.view.resetTransform()
        self.zoom_factor = 1.0

    def fit_graph(self) -> None:
        """Zoom out until every node fits; if it still won't, clamp to min zoom."""
        rect = self.scene.itemsBoundingRect()
        if rect.isEmpty():
            return
        self.view.resetTransform()
        self.view.fitInView(rect, Qt.KeepAspectRatio)
        scale = self.view.transform().m11()
        clamped = max(_MIN_ZOOM, min(_MAX_ZOOM, scale))
        if abs(clamped - scale) > 1e-9:
            self.view.resetTransform()
            self.view.scale(clamped, clamped)
            self.view.centerOn(rect.center())
            scale = clamped
        self.zoom_factor = scale

    def _layout_positions(self, graph: WorkflowGraph) -> dict[str, QPointF]:
        nodes_by_id = {node.node_id: node for node in graph.nodes}
        columns: dict[int, list[str]] = defaultdict(list)
        for node in graph.nodes:
            columns[node.level - 1].append(node.node_id)

        column_heights = {
            column: (len(node_ids) - 1) * _Y_GAP
            for column, node_ids in columns.items()
        }
        max_height = max(column_heights.values(), default=0.0)
        center_y = 70.0 + max_height / 2.0

        positions: dict[str, QPointF] = {}
        for column, node_ids in columns.items():
            ordered_ids = sorted(node_ids, key=lambda item: nodes_by_id[item].name)
            start_y = center_y - ((len(ordered_ids) - 1) * _Y_GAP) / 2.0
            for row, node_id in enumerate(ordered_ids):
                positions[node_id] = QPointF(420.0 + column * _X_GAP, start_y + row * _Y_GAP)

        all_y = [point.y() for point in positions.values()] or [70.0]
        center_y = (min(all_y) + max(all_y)) / 2.0
        max_level = max(columns.keys(), default=0)
        positions["INI"] = QPointF(20.0, center_y)
        positions["END"] = QPointF(420.0 + (max_level + 1) * _X_GAP, center_y)
        return positions

    def _draw_node(self, node: WorkflowGraphNode, pos: QPointF) -> None:
        controls = " | ".join(node.control_groups) if node.control_groups else "none"
        detail = _NodeDetail(
            title=node.name,
            subtitle=f"Step {node.level} \u00b7 batch '{node.batch_value}' \u00b7 "
            f"control group: {controls} \u00b7 "
            + (
                "used for decontamination"
                if node.run_decontamination
                else "skipped for decontamination"
            ),
            sample_ids=list(node.sample_ids),
            control_ids=list(node.control_ids),
            prior_control_ids=list(node.prior_control_ids),
        )
        body = (
            f"{node.name}\nsamples: {detail.sample_total}"
            f"\ncontrols: {len(detail.control_ids)}"
        )
        self._add_box(node.node_id, pos, body, detail, skipped=not node.run_decontamination)

    def _draw_step_summary(
        self,
        key: str,
        pos: QPointF,
        graph: WorkflowGraph,
        level: int,
        step_nodes: list[WorkflowGraphNode],
    ) -> None:
        step_name = self._step_name(graph, level, step_nodes)
        control_groups = self._step_control_groups(graph, level, step_nodes)
        controls = ", ".join(control_groups) if control_groups else "none"
        batch_label = "batch" if len(step_nodes) == 1 else "batches"
        batches = ", ".join(sorted(node.batch_value for node in step_nodes))
        sample_ids = sorted({item for node in step_nodes for item in node.sample_ids})
        control_ids = sorted({item for node in step_nodes for item in node.control_ids})
        prior_ids = sorted({item for node in step_nodes for item in node.prior_control_ids})
        detail = _NodeDetail(
            title=step_name,
            subtitle=f"Step {level} \u00b7 {len(step_nodes)} {batch_label}: {batches} \u00b7 "
            f"control group: {controls}",
            sample_ids=sample_ids,
            control_ids=control_ids,
            prior_control_ids=prior_ids,
        )
        body = (
            f"{step_name}\n{len(step_nodes)} {batch_label}"
            f"\nsamples: {detail.sample_total}\ncontrols: {len(detail.control_ids)}"
        )
        skipped = all(not node.run_decontamination for node in step_nodes)
        self._add_box(key, pos, body, detail, skipped=skipped)

    def _add_box(
        self, key: str, pos: QPointF, body: str, detail: _NodeDetail, *, skipped: bool
    ) -> None:
        rect = _NodeItem(pos.x(), pos.y(), _BOX_W, _BOX_H, self._tooltip(detail))
        self.scene.addItem(rect)
        # A dashed, muted box marks a step excluded from decontamination now that
        # the node no longer spends a whole line on the word "skip".
        if skipped:
            rect.setPen(QPen(QColor(_SKIP_BORDER), 1.2, Qt.DashLine))
            rect.setBrush(QBrush(QColor(_SKIP_FILL)))
        else:
            rect.setPen(QPen(QColor(_NODE_BORDER), 1.2))
            rect.setBrush(QBrush(QColor(_NODE_FILL)))
        rect.setData(_NODE_KEY, key)

        text = self.scene.addText(body)
        text.setDefaultTextColor(QColor(_SKIP_TEXT if skipped else _NODE_TEXT))
        text.setTextWidth(_BOX_W - 18)
        # A child of the box, and deaf to the mouse, so a click anywhere on the node
        # reaches the box and the tooltip is the box's. The box sits at the scene
        # origin with its rect carrying the offset, so child coordinates are scene ones.
        text.setParentItem(rect)
        text.setPos(pos.x() + 10, pos.y() + 8)
        text.setAcceptedMouseButtons(Qt.NoButton)
        text.setAcceptHoverEvents(False)

        self._node_items[key] = rect
        self._node_texts[key] = text
        self._node_details[key] = detail

    def _tooltip(self, detail: _NodeDetail) -> str:
        lines = [f"<b>{html.escape(detail.title)}</b>", html.escape(detail.subtitle)]
        lines.append(self._tooltip_line("Samples", detail.sample_ids))
        lines.append(self._tooltip_line("Controls", detail.control_ids))
        if detail.prior_control_ids:
            lines.append(
                self._tooltip_line("Controls from previous step", detail.prior_control_ids)
            )
        lines.append("<i>Click the node for the full list.</i>")
        return "<br>".join(lines)

    def _tooltip_line(self, title: str, ids: list[str]) -> str:
        if not ids:
            return f"{title} (0): none"
        listed = ", ".join(html.escape(item) for item in ids[:_TOOLTIP_LIMIT])
        if len(ids) > _TOOLTIP_LIMIT:
            listed += f", \u2026 (+{len(ids) - _TOOLTIP_LIMIT} more)"
        return f"{title} ({len(ids)}): {listed}"

    def _draw_system_node(self, label: str, pos: QPointF) -> None:
        rect = self.scene.addRect(pos.x(), pos.y(), _BOX_W, _BOX_H)
        rect.setPen(QPen(QColor(_SYSTEM_BORDER), 1.4))
        rect.setBrush(QBrush(QColor(_SYSTEM_FILL)))
        text = self.scene.addText(label)
        text.setDefaultTextColor(QColor(_SYSTEM_TEXT))
        text.setPos(pos.x() + 16, pos.y() + 30)

    def _draw_edge(
        self,
        parent: str,
        child: str,
        parent_pos: QPointF,
        child_pos: QPointF,
        *,
        weak: bool = False,
    ) -> None:
        start = QPointF(parent_pos.x() + _BOX_W, parent_pos.y() + _BOX_H / 2.0)
        end = QPointF(child_pos.x(), child_pos.y() + _BOX_H / 2.0)
        # Thin, dashed and pale when no sample travels it, so the eye still reads the
        # workflow's sample lanes first and the pooled controls second.
        color = QColor(_WEAK_EDGE_COLOR if weak else _EDGE_COLOR)
        pen = QPen(color, 1.0 if weak else 1.6)
        if weak:
            pen.setStyle(Qt.DashLine)
        line = self.scene.addLine(start.x(), start.y(), end.x(), end.y(), pen)

        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = max((dx * dx + dy * dy) ** 0.5, 1.0)
        ux = dx / length
        uy = dy / length
        px = -uy
        py = ux
        size = 9.0
        width = 5.0
        left = QPointF(end.x() - ux * size + px * width, end.y() - uy * size + py * width)
        right = QPointF(end.x() - ux * size - px * width, end.y() - uy * size - py * width)
        # The head keeps a solid outline; a dashed one only looks broken.
        head = self.scene.addPolygon(QPolygonF([end, left, right]), QPen(color, 1.0), QBrush(color))
        self._edge_items[(parent, child)] = [line, head]

    def _membership(
        self, graph: WorkflowGraph
    ) -> tuple[dict[str, frozenset[str]], dict[tuple[str, str], frozenset[str]]]:
        """Every box's and arrow's rows as sets, built once per graph.

        The graph keeps them as lists, and `in` on a list is a walk, so without this a
        single search reads every ID in the diagram from end to end.
        """
        if self._node_rows is None or self._edge_rows is None:
            self._node_rows = {
                node.node_id: frozenset(node.sample_ids)
                | frozenset(node.control_ids)
                | frozenset(node.prior_control_ids)
                for node in graph.nodes
            }
            self._edge_rows = {
                (edge.parent_id, edge.child_id): frozenset(edge.sample_ids)
                | frozenset(edge.control_ids)
                for edge in graph.edges
            }
        return self._node_rows, self._edge_rows

    def _forget_membership(self) -> None:
        self._node_rows = None
        self._edge_rows = None

    def _apply_highlight(self, graph: WorkflowGraph) -> None:
        kind, value = self._highlight
        self._highlight_hits = 0
        if not value:
            return
        if self._simplified:
            found = self._simplified_highlight(graph, kind, value)
        else:
            found = self._detailed_highlight(graph, kind, value)

        for key in found.strong:
            self._paint_node(key, found.shades.strong_border, found.shades.strong_fill)
        for key in found.weak:
            self._paint_node(key, found.shades.weak_border, found.shades.weak_fill)
        for edge in found.edges:
            self._paint_edge(edge, found.edge_color)
        self._highlight_hits = found.hits

    def _detailed_highlight(self, graph: WorkflowGraph, kind: str, value: str) -> _Highlight:
        if kind == KIND_STEP:
            # One step is one column, and a column has no arrows inside it to paint.
            return _Highlight(
                strong=[node.node_id for node in graph.nodes if node.step_column == value]
            )
        if kind == KIND_BATCH:
            return self._batch_highlight(graph, value)
        return self._row_highlight(graph, value)

    def _row_highlight(self, graph: WorkflowGraph, row_id: str) -> _Highlight:
        node_rows, edge_rows = self._membership(graph)
        here = [node for node in graph.nodes if row_id in node_rows[node.node_id]]
        if not here:
            return _Highlight()
        samples = [node.node_id for node in here if row_id in node.sample_ids]
        if samples:
            found = _Highlight(strong=samples)
        else:
            # Deep where the step draws on it, pale where it is only along for the ride.
            found = _Highlight(
                strong=[node.node_id for node in here if row_id in node.control_ids],
                weak=[node.node_id for node in here if row_id in node.prior_control_ids],
                shades=_RED,
                edge_color=_CONTROL_BORDER,
            )
        # A row is either a sample or a control, so whichever list an arrow records it
        # in, its being there means this row travelled it. Read rather than re-derived,
        # the path cannot drift from the one the graph was built with.
        found.edges = [edge for edge, rows in edge_rows.items() if row_id in rows]
        on_path = {node.node_id for node in here}
        found.edges.extend((leaf, end) for leaf, end in graph.system_edges if leaf in on_path)
        return found

    def _batch_highlight(self, graph: WorkflowGraph, name: str) -> _Highlight:
        node_rows, edge_rows = self._membership(graph)
        target = next((node for node in graph.nodes if node.name == name), None)
        if target is None:
            return _Highlight()
        # Where this batch's own rows reach, and nowhere further: a plate this batch
        # shares with another one does not drag that other batch's onward route in.
        members = node_rows[target.node_id]
        found = _Highlight(
            strong=[target.node_id],
            weak=[
                node.node_id
                for node in graph.nodes
                if node.node_id != target.node_id and members & node_rows[node.node_id]
            ],
            edge_color=_TOUCHED_BORDER,
        )
        found.edges = [edge for edge, rows in edge_rows.items() if members & rows]
        on_path = set(found.strong) | set(found.weak)
        found.edges.extend((leaf, end) for leaf, end in graph.system_edges if leaf in on_path)
        return found

    def _simplified_highlight(self, graph: WorkflowGraph, kind: str, value: str) -> _Highlight:
        if kind == KIND_STEP:
            levels = {node.level for node in graph.nodes if node.step_column == value}
            return self._folded_highlight(graph, levels, set(), chain=False)
        if kind == KIND_BATCH:
            node_rows, _ = self._membership(graph)
            target = next((node for node in graph.nodes if node.name == value), None)
            if target is None:
                return _Highlight()
            members = node_rows[target.node_id]
            touched = {
                node.level for node in graph.nodes if members & node_rows[node.node_id]
            }
            return self._folded_highlight(
                graph, {target.level}, touched - {target.level}, edge_color=_TOUCHED_BORDER
            )
        sample_levels = {node.level for node in graph.nodes if value in node.sample_ids}
        if sample_levels:
            return self._folded_highlight(graph, sample_levels, set())
        # A step it is a source in outranks one it is only carried through, so a folded
        # step still gets a single colour.
        source_levels = {node.level for node in graph.nodes if value in node.control_ids}
        carried_levels = {
            node.level for node in graph.nodes if value in node.prior_control_ids
        }
        return self._folded_highlight(
            graph,
            source_levels,
            carried_levels - source_levels,
            shades=_RED,
            edge_color=_CONTROL_BORDER,
        )

    def _folded_highlight(
        self,
        graph: WorkflowGraph,
        strong_levels: set[int],
        weak_levels: set[int],
        *,
        shades: _Shades = _GREEN,
        edge_color: str = _SAMPLE_BORDER,
        chain: bool = True,
    ) -> _Highlight:
        found = _Highlight(
            strong=[step_key(level) for level in sorted(strong_levels)],
            weak=[step_key(level) for level in sorted(weak_levels)],
            shades=shades,
            edge_color=edge_color,
        )
        lit = strong_levels | weak_levels
        if not chain or not lit:
            return found
        levels = sorted({node.level for node in graph.nodes})
        keys = ["INI"] + [step_key(level) for level in levels] + ["END"]
        on_path = {step_key(level) for level in lit} | {"INI", "END"}
        found.edges = [
            (parent, child)
            for parent, child in zip(keys, keys[1:])
            if parent in on_path and child in on_path
        ]
        return found

    def _paint_node(self, key: str, border: str, fill: str) -> None:
        rect = self._node_items.get(key)
        if rect is None:
            return
        rect.setPen(QPen(QColor(border), 2.2))
        rect.setBrush(QBrush(QColor(fill)))
        text = self._node_texts.get(key)
        if text is not None:
            text.setDefaultTextColor(QColor(_NODE_TEXT))

    def _paint_edge(self, edge: tuple[str, str], color: str) -> None:
        items = self._edge_items.get(edge)
        if not items:
            return
        pen = QPen(QColor(color), 2.6)
        for item in items:
            item.setPen(pen)
        items[-1].setBrush(QBrush(QColor(color)))

    def _show_node_details(self, key: str) -> None:
        detail = self._node_details.get(key)
        if detail is None:
            return
        NodeDetailsDialog(detail, self).exec()


def step_key(level: int) -> str:
    return f"STEP{level}"
