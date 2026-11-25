"""Three-column main view for a single dataset tab.

Layout: [Input Summary] | [DAG + Result] | [Concentration Table + Run].

This is where a run is orchestrated: it turns the right column's state into a
`BackendRunRequest`, creates the run directory, snapshots the three columns, and
hands everything to a `RunController`. It performs no computation itself.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QMessageBox,
    QSplitter,
    QSplitterHandle,
    QStyle,
    QVBoxLayout,
    QWidget,
)


class _ClampingHandle(QSplitterHandle):
    """Splitter handle that never drags past its two neighbours' minimums.

    ``QSplitter.moveSplitter`` isn't virtual, so a Python override is bypassed
    by real mouse drags (they cascade into the far panels once the neighbour
    hits its minimum). Instead we own the drag here and feed ``moveSplitter`` a
    position that is already clamped, so only the two adjacent panels resize.
    """

    def __init__(self, orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self._index = 0
        self._mouse_start = 0
        self._handle_start = 0

    def _pick(self, point) -> int:
        return point.x() if self.orientation() == Qt.Horizontal else point.y()

    def _handle_index(self) -> int:
        splitter = self.splitter()
        for i in range(1, splitter.count()):
            if splitter.handle(i) is self:
                return i
        return 0

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._index = self._handle_index()
        self._mouse_start = self._pick(event.globalPosition().toPoint())
        self._handle_start = self._pick(self.pos())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        splitter = self.splitter()
        index = self._index
        if index <= 0:
            super().mouseMoveEvent(event)
            return
        delta = self._pick(event.globalPosition().toPoint()) - self._mouse_start
        target = self._handle_start + delta
        lo, hi = self._bounds(index)
        splitter.moveSplitter(max(lo, min(target, hi)), index)

    def _bounds(self, index: int) -> tuple[int, int]:
        splitter = self.splitter()
        left = splitter.widget(index - 1)
        right = splitter.widget(index)
        sizes = splitter.sizes()
        handle = splitter.handleWidth()
        left_edge = sum(sizes[: index - 1]) + handle * (index - 1)
        right_edge = sum(sizes[: index + 1]) + handle * index
        lo = left_edge + self._min_length(left)
        hi = right_edge - handle - self._min_length(right)
        return lo, max(lo, hi)

    def _min_length(self, widget: QWidget) -> int:
        if widget is None:
            return 0
        if self.orientation() == Qt.Horizontal:
            return max(widget.minimumWidth(), widget.minimumSizeHint().width())
        return max(widget.minimumHeight(), widget.minimumSizeHint().height())


class _NonCascadingSplitter(QSplitter):
    """Splitter whose handles stop at the adjacent panels' minimum sizes rather
    than cascading the resize into the far panels."""

    def createHandle(self) -> QSplitterHandle:  # noqa: N802 (Qt override)
        return _ClampingHandle(self.orientation(), self)


from dmcscrub_app.backend import paths
from dmcscrub_app.backend.cscrub_checker import check_cscrub_inputs
from dmcscrub_app.backend.dmcscrub_checker import check_dmcscrub_inputs
from dmcscrub_app.backend.contracts import (
    STAGE_FITTING,
    BackendRunRequest,
    BackendRunResult,
    ColumnMapping,
)
from dmcscrub_app.core.workflow import (
    WorkflowStepConfig,
    build_workflow_graph,
    search_entries,
)
from dmcscrub_app.ui.controllers.run_controller import RunController
from dmcscrub_app.ui.models import (
    ALGORITHM_C_SCRUB,
    DatasetConfig,
    DatasetVM,
)
from dmcscrub_app.ui.search_index import SearchIndex
from dmcscrub_app.ui.view_snapshot import build_snapshot, write_snapshot
from dmcscrub_app.ui.widgets.concentration_color_panel import ConcentrationColorPanel
from dmcscrub_app.ui.widgets.dag_canvas import DagCanvas
from dmcscrub_app.ui.widgets.input_summary_panel import InputSummaryPanel
from dmcscrub_app.ui.widgets.run_progress import RunProgress


BUTTON_RUN_ANYWAY = "Run anyway"
BUTTON_RE_ENTER = "Re-enter data"


def _reversed_button_layout() -> bool:
    """Whether this platform lays a row of dialog buttons out right to left."""
    style = QApplication.style()
    if style is None:
        return False
    # `.value`, because `styleHint` returns a plain int and PySide6's ButtonLayout is
    # a true Python enum: comparing the two directly is quietly always False.
    return style.styleHint(QStyle.SH_DialogButtonLayout) == QDialogButtonBox.MacLayout.value


class DatasetView(QWidget):
    """Composes the three columns for one dataset and orchestrates a run."""

    def __init__(self, dataset: DatasetVM) -> None:
        super().__init__()
        self._dataset = dataset
        self._last_result: BackendRunResult | None = None
        self._pending_notices: list[str] = []
        self._pending_warnings: list[str] = []
        self._notes: list[str] = []
        self._popup_shown = False

        self.summary_panel = InputSummaryPanel()
        self.dag = DagCanvas()
        self.run_progress = RunProgress()
        self.control_panel = ConcentrationColorPanel(dataset.concentrations)
        self._dag_rebuild_timer = QTimer(self)
        self._dag_rebuild_timer.setSingleShot(True)
        self._dag_rebuild_timer.setInterval(150)
        self._dag_rebuild_timer.timeout.connect(self._apply_scheduled_dag_rebuild)

        # Center column: Workflow above Result, two cards of the same width that the
        # user can rebalance. Result is hidden until a run starts, and the space it
        # then takes comes out of the diagram rather than out of the window.
        self._center_splitter = QSplitter(Qt.Vertical)
        self._center_splitter.addWidget(self.dag)
        self._center_splitter.addWidget(self.run_progress)
        self._center_splitter.setStretchFactor(0, 1)
        self._center_splitter.setStretchFactor(1, 0)
        self._center_splitter.setChildrenCollapsible(False)

        splitter = _NonCascadingSplitter(Qt.Horizontal)
        splitter.addWidget(self.summary_panel)
        splitter.addWidget(self._center_splitter)
        splitter.addWidget(self.control_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([300, 640, 360])
        splitter.setChildrenCollapsible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(splitter)

        self.controller = RunController(self)
        self.controller.stage_changed.connect(self._on_stage_changed)
        self.controller.notice.connect(self._pending_notices.append)
        self.controller.warning.connect(self._pending_warnings.append)
        self.controller.finished.connect(self._on_finished)
        self.controller.failed.connect(self._on_failed)
        self.controller.cancelled.connect(self._on_cancelled)
        self.controller.running_changed.connect(self.control_panel.set_running)

        self._run_guard: Callable[[], bool] | None = None
        self._bind(dataset)
        self.control_panel.run_clicked.connect(self._on_run_requested)
        self.control_panel.changed.connect(self._schedule_dag_rebuild)
        self.run_progress.cancel_clicked.connect(self._on_cancel_clicked)
        self.summary_panel.find.selected.connect(self._on_find_selected)
        self.summary_panel.find.cleared.connect(self._on_find_cleared)

    @property
    def config(self) -> DatasetConfig:
        return self._dataset.config

    @property
    def is_running(self) -> bool:
        return self.controller.is_running

    @property
    def active_run_dir(self) -> Path | None:
        return self.controller.run_dir if self.controller.is_running else None

    def rename(self, name: str) -> None:
        """Keep the dataset model in sync with its editable tab title."""
        config = replace(self._dataset.config, name=name)
        self._dataset = replace(self._dataset, config=config)

    def status_text(self) -> str:
        pipeline = self._dataset.pipeline
        return (
            f"{self._dataset.config.name}   \u00b7   "
            f"{pipeline.total_samples} samples   \u00b7   {len(pipeline.steps)} steps"
        )

    def set_run_guard(self, guard: Callable[[], bool] | None) -> None:
        """Set an optional application-level check that runs before start_run."""
        self._run_guard = guard

    def _on_run_requested(self) -> None:
        if self._run_guard is not None and not self._run_guard():
            return
        self.start_run()

    def _bind(self, dataset: DatasetVM) -> None:
        self.summary_panel.set_summary(dataset.summary)
        self.control_panel.set_run_method(dataset.config.algorithm)
        self.control_panel.set_pipeline(dataset.pipeline)
        # Straight from the tables rather than from the graph, so a sample the DAG
        # leaves out is still findable and can be told it is missing. Steps and batches
        # have no such source and are refreshed with the graph instead.
        self._search_rows = search_entries(dataset.input_data) if dataset.input_data else []
        self.summary_panel.find.reset()
        # Draw the initial DAG from the panel's starting configuration so the
        # middle graph always matches the right column.
        self._rebuild_dag()

    def _on_find_selected(self, kind: str, value: str) -> None:
        if self.dag.highlight(kind, value) == 0:
            self.summary_panel.find.set_hint(
                f"'{value}' is not part of any node in the diagram."
            )

    def _on_find_cleared(self) -> None:
        self.dag.highlight()

    def _current_step_configs(self) -> list[WorkflowStepConfig]:
        """Right-panel state -> ordered WorkflowStepConfig list for the DAG.

        The list order is the user's current step order; "Show in DAG" maps to
        ``enabled`` (which drives the DAG levels).
        """
        configs: list[WorkflowStepConfig] = []
        for entry in self.control_panel.step_config():
            configs.append(
                WorkflowStepConfig(
                    column=entry["key"],
                    enabled=bool(entry.get("in_dag", True)),
                    control_groups=list(entry.get("control_groups", [])),
                    run_decontamination=bool(
                        entry.get("in_decontamination", True)
                    ),
                )
            )
        return configs

    def _rebuild_dag(self, preserve_view: bool = False) -> None:
        """Redraw the middle DAG as the real, level-ordered workflow graph.

        Uses ``build_workflow_graph`` so nodes are the per-batch groups of each
        step, laid out by level (INI -> step 1 -> step 2 -> ... -> END) with the
        real parent/child links, matching the previous branch's DAG.

        ``preserve_view`` keeps the current zoom/pan (used for edits from the
        right panel); the initial draw uses the default framing.
        """
        input_data = self._dataset.input_data
        if input_data is None:
            self.dag.clear()
            return
        graph = build_workflow_graph(input_data, self._current_step_configs())
        self.dag.set_graph(graph, preserve_view=preserve_view)
        # The step and batch names on offer are the ones now drawn, so this has to
        # follow every rebuild, not just the first.
        self.summary_panel.find.set_index(SearchIndex.from_graph(graph, self._search_rows))

    def _schedule_dag_rebuild(self) -> None:
        """Coalesce rapid panel edits while keeping the current graph visible."""
        self.dag.set_update_pending(True)
        self._dag_rebuild_timer.start()

    def _apply_scheduled_dag_rebuild(self) -> None:
        try:
            self._rebuild_dag(preserve_view=True)
        finally:
            self.dag.set_update_pending(False)

    # --- running ------------------------------------------------------------

    def start_run(self) -> None:
        """Validate first, then create the run directory."""
        if self.controller.is_running:
            return
        self._start_concentration_run()

    def _start_concentration_run(self) -> None:
        self._dag_rebuild_timer.stop()
        config = self._dataset.config
        if config.algorithm == ALGORITHM_C_SCRUB:
            checked = check_cscrub_inputs(
                config.count_path,
                config.metadata_path,
                sample_column=config.mapping.sample,
                concentration_column=config.mapping.concentration,
            )
        else:
            checked = check_dmcscrub_inputs(
                config.count_path,
                config.metadata_path,
                sample_column=config.mapping.sample,
                concentration_column=config.mapping.concentration,
                batch_column=config.mapping.batch,
                label_column=config.mapping.label,
                positive_value=config.mapping.positive_value,
            )

        if checked.hard_errors:
            box = QMessageBox(self)
            box.setWindowTitle("Cannot Start Run")
            box.setIcon(QMessageBox.Critical)
            box.setText("The input files cannot be aligned safely.")
            box.setInformativeText(checked.hard_errors[0])
            box.setDetailedText("\n".join(checked.hard_errors))
            box.exec()
            return

        repair_invalid = False
        if checked.repairable_issues:
            box = QMessageBox(self)
            box.setWindowTitle("Invalid Input Values")
            box.setIcon(QMessageBox.Warning)
            box.setText(
                f"{len(checked.repairable_issues)} input problem(s) must be resolved."
            )
            box.setInformativeText(
                "Run Anyway replaces invalid numeric cells with 0, uses '0' for "
                "empty batch values, and keeps any resulting zero-read rows."
            )
            box.setDetailedText("\n".join(checked.repairable_issues))
            self._add_answers(
                box,
                [BUTTON_RUN_ANYWAY, BUTTON_RE_ENTER],
                default=BUTTON_RUN_ANYWAY,
            )
            if (
                self.ask_preflight("concentration_input", box)
                != BUTTON_RUN_ANYWAY
            ):
                return
            repair_invalid = True

        input_data = self._dataset.input_data
        if input_data is None:
            QMessageBox.critical(self, "Cannot Run", "This dataset has no loaded tables.")
            return
        step_configs = self._current_step_configs()
        graph = build_workflow_graph(input_data, step_configs)
        self.dag.set_graph(graph, preserve_view=True)
        selections = self._selections(step_configs)

        run_dir = paths.create_run_dir(config.name)
        write_snapshot(
            run_dir / paths.VIEW_SNAPSHOT,
            build_snapshot(
                self._dataset.summary,
                self._dataset.pipeline,
                selections,
                graph,
                algorithm=config.algorithm,
                concentrations=self._dataset.concentrations,
            ),
        )
        request = BackendRunRequest(
            dataset_name=config.name,
            count_path=config.count_path,
            metadata_path=config.metadata_path,
            column_mapping=ColumnMapping(
                sample_name=config.mapping.sample,
                concentration=config.mapping.concentration,
                batch=config.mapping.batch,
                label=config.mapping.label,
                positive_value=config.mapping.positive_value,
            ),
            run_dir=run_dir,
            algorithm=config.algorithm,
            repair_invalid=repair_invalid,
        )

        self._pending_notices = []
        self._pending_warnings = []
        self._notes = [
            "Input checks passed"
            if not repair_invalid
            else "Run Anyway selected \u00b7 invalid values replaced with 0"
        ]
        self._popup_shown = False
        self._last_result = None
        self.run_progress.start(run_dir, algorithm=config.algorithm)
        self.run_progress.set_input_summary(samples=checked.counts.shape[0])
        self.run_progress.set_notes(self._notes)
        self._reveal_result_card()
        self.controller.start(request)

    def cancel_run(self) -> None:
        self.controller.cancel()

    def ask_preflight(self, kind: str, box: QMessageBox) -> str:
        """Show a pre-flight question and return the label of the button clicked.

        The single place where a pre-flight question blocks, and the reason answers
        are identified by label rather than by button object: checks replace this
        method to answer without an event loop. `kind` is passed for their benefit
        too, since a window title is not something macOS shows or keeps.
        """
        box.exec()
        clicked = box.clickedButton()
        return clicked.text().replace("&", "") if clicked is not None else ""

    def _add_answers(self, box: QMessageBox, labels: list[str], default: str) -> None:
        """Add the answers so they read left to right as given, on every platform.

        Two things stand between the buttons and a fixed order. `QMessageBox`
        arranges by role, and the macOS policy puts the reject button ahead of the
        accept ones, which is what used to strand "Re-enter data" in the middle; one
        role for every answer settles that. That policy then lays the row out right
        to left, so the insertion order has to be flipped there to read the same way
        on screen. Escape still means the last answer, which is always the one that
        does not run.
        """
        order = list(reversed(labels)) if _reversed_button_layout() else list(labels)
        buttons = {label: box.addButton(label, QMessageBox.AcceptRole) for label in order}
        box.setDefaultButton(buttons[default])
        box.setEscapeButton(buttons[labels[-1]])

    def _reveal_result_card(self) -> None:
        """Seat the Result card by shrinking the diagram, keeping the column's height."""
        total = self._center_splitter.height()
        if total <= 0:
            return
        floor = self.dag.minimumSizeHint().height()
        height = min(self.run_progress.sizeHint().height(), max(0, total - floor))
        self._center_splitter.setSizes([total - height, height])

    def _selections(self, configs: list[WorkflowStepConfig]) -> list[dict]:
        """What the user selected, for the snapshot's read-only right column."""
        return [
            {
                "order": order,
                "column": config.column,
                "control_groups": list(config.control_groups),
                "in_dag": config.enabled,
                "in_decontamination": config.run_decontamination,
            }
            for order, config in enumerate(configs, start=1)
        ]

    # --- controller signals -------------------------------------------------

    def _on_stage_changed(self, stage: str) -> None:
        self.run_progress.set_stage(stage)
        # The popup fires when input building ends, not when the run does: at this
        # point the fit has not started, so a user who reads "step 2 was skipped"
        # can still cancel instead of waiting out a run they do not want.
        if stage == STAGE_FITTING and not self._popup_shown:
            self._popup_shown = True
            self._show_notices_popup()

    def _on_finished(self, result: BackendRunResult) -> None:
        self._last_result = result
        self.run_progress.finish(result.run_dir)
        self._refresh_notes()

    def _on_failed(self, message: str) -> None:
        self.run_progress.fail(message)
        self._refresh_notes()
        QMessageBox.critical(self, "Run Failed", message)

    def _on_cancelled(self) -> None:
        self.run_progress.cancel()
        self._refresh_notes()

    def _on_cancel_clicked(self) -> None:
        if not self.controller.is_running:
            return
        confirm = QMessageBox.question(
            self,
            "Cancel Run",
            "Stop this run? The partial run folder is kept but contains no results.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self.controller.cancel()

    # --- notices ------------------------------------------------------------

    def _show_notices_popup(self) -> None:
        if not self._pending_notices and not self._pending_warnings:
            return
        blocks: list[str] = []
        if self._pending_notices:
            blocks.append("\n".join(f"\u2022 {text}" for text in self._pending_notices))
        if self._pending_warnings:
            blocks.append("\n".join(f"\u2022 {text}" for text in self._pending_warnings))
        box = QMessageBox(self)
        box.setWindowTitle("Run Notes")
        box.setIcon(QMessageBox.Warning if self._pending_warnings else QMessageBox.Information)
        box.setText("The run is continuing, but some inputs were skipped or excluded.")
        box.setDetailedText("\n\n".join(blocks))
        box.setInformativeText(blocks[0][:400])
        # Non-modal: closing or ignoring it must not touch the child process.
        box.setWindowModality(Qt.NonModal)
        box.show()
        self._refresh_notes()

    def _add_note(self, text: str) -> None:
        self._notes.append(text)
        self._refresh_notes()

    def _refresh_notes(self) -> None:
        lines = list(self._notes)
        lines.extend(self._pending_notices)
        lines.extend(self._pending_warnings)
        self.run_progress.set_notes(lines)
