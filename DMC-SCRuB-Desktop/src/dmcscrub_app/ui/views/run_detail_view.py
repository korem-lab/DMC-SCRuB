"""Read-only page for one past run: the same three columns, none of the wiring.

It reuses `DatasetView`'s four widgets but not `DatasetView` itself. That class owns
a `RunController`, a Run button and the whole editing signal graph; bolting a
`read_only` flag onto it would tangle run orchestration together with static
display. Assembling the same widgets separately keeps both simple.

Nothing is recomputed and nothing is re-run: the left and middle columns come from
`view_snapshot.json`, the conclusion from `run_manifest.json`, and the downloads
from the files this run already wrote.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dmcscrub_app.backend import history, manifest, paths
from dmcscrub_app.core.workflow import search_entries_from_graph
from dmcscrub_app.ui.search_index import SearchIndex
from dmcscrub_app.ui.view_snapshot import (
    SnapshotVersionError,
    concentrations_from_snapshot,
    graph_from_snapshot,
    pipeline_from_snapshot,
    read_snapshot,
    selections_from_snapshot,
    summary_from_snapshot,
)
from dmcscrub_app.ui.widgets.concentration_color_panel import ConcentrationColorPanel
from dmcscrub_app.ui.widgets.dag_canvas import DagCanvas
from dmcscrub_app.ui.widgets.input_summary_panel import InputSummaryPanel
from dmcscrub_app.ui.widgets.result_files_widget import ResultFilesWidget

TITLE_MAX_LENGTH = 24


class RunDetailView(QWidget):
    """One tab per past run; several can be open at once to compare runs."""

    def __init__(self, summary: history.RunSummary) -> None:
        super().__init__()
        self.summary = summary
        self._run_dir = summary.run_dir

        self.summary_panel = InputSummaryPanel()
        self.dag = DagCanvas()
        try:
            snapshot = read_snapshot(self._run_dir / paths.VIEW_SNAPSHOT)
            concentrations = concentrations_from_snapshot(snapshot)
        except (OSError, ValueError):
            concentrations = []
        self.control_panel = ConcentrationColorPanel(concentrations)
        self.control_panel.set_run_method(summary.algorithm)
        self.control_panel.set_read_only(True)

        self._conclusion = QLabel("")
        self._conclusion.setObjectName("metricLabel")
        self._conclusion.setWordWrap(True)

        self._notes = QTextEdit()
        self._notes.setObjectName("runNotes")
        self._notes.setReadOnly(True)
        self._notes.setMaximumHeight(110)

        self.result_files = ResultFilesWidget()
        open_folder = QPushButton("Open folder")
        open_folder.clicked.connect(self._open_folder)
        open_log = QPushButton("Open log")
        open_log.clicked.connect(self._open_log)
        self.result_files.add_action_button(open_folder)
        self.result_files.add_action_button(open_log)

        result_frame = QFrame()
        result_frame.setObjectName("progressFrame")
        result_layout = QVBoxLayout(result_frame)
        result_layout.setContentsMargins(16, 14, 16, 14)
        result_layout.setSpacing(8)
        title = QLabel("Result")
        title.setObjectName("panelTitle")
        result_layout.addWidget(title)
        result_layout.addWidget(self._conclusion)
        result_layout.addWidget(self._notes)
        result_layout.addWidget(self.result_files)

        center = QSplitter(Qt.Vertical)
        center.addWidget(self.dag)
        center.addWidget(result_frame)
        center.setStretchFactor(0, 1)
        center.setStretchFactor(1, 0)
        center.setSizes([460, 220])
        center.setChildrenCollapsible(False)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.summary_panel)
        splitter.addWidget(center)
        splitter.addWidget(self.control_panel)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 640, 360])
        splitter.setChildrenCollapsible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(splitter)

        self.summary_panel.find.selected.connect(self._on_find_selected)
        self.summary_panel.find.cleared.connect(self._on_find_cleared)

        self._load()

    @property
    def run_id(self) -> str:
        return self.summary.run_id

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    def tab_title(self) -> str:
        name = self.summary.dataset_name
        if len(name) > TITLE_MAX_LENGTH:
            name = name[: TITLE_MAX_LENGTH - 1] + "\u2026"
        return name

    def _load(self) -> None:
        self.result_files.set_run_dir(
            self._run_dir if self.summary.has_results else None
        )
        self._load_snapshot()
        self._load_manifest()

    def _load_snapshot(self) -> None:
        path = self._run_dir / paths.VIEW_SNAPSHOT
        try:
            payload = read_snapshot(path)
        except SnapshotVersionError as exc:
            # Downloads still work; only the reconstructed view is unavailable.
            self._conclusion.setText(str(exc))
            return
        except (OSError, ValueError):
            self._conclusion.setText("This run has no view snapshot, so its setup cannot be shown.")
            return

        graph = graph_from_snapshot(payload)
        self.summary_panel.set_summary(summary_from_snapshot(payload))
        self.control_panel.set_pipeline(pipeline_from_snapshot(payload))
        self.control_panel.apply_selections(selections_from_snapshot(payload))
        self.control_panel.set_read_only(True)
        self.dag.set_graph(graph)
        # The saved graph is all this page has to search; the count table it came
        # from may be long gone, and re-reading it could describe different data.
        self.summary_panel.find.set_index(
            SearchIndex.from_graph(graph, search_entries_from_graph(graph))
        )

    def _on_find_selected(self, kind: str, value: str) -> None:
        if self.dag.highlight(kind, value) == 0:
            self.summary_panel.find.set_hint(
                f"'{value}' is not part of any node in the diagram."
            )

    def _on_find_cleared(self) -> None:
        self.dag.highlight()

    def _load_manifest(self) -> None:
        payload = manifest.read_manifest(self._run_dir) or {}
        lines: list[str] = []

        status = payload.get("status")
        algorithm = payload.get("algorithm") or self.summary.algorithm
        if status == manifest.STATUS_SUCCESS:
            conclusion_parts = [f"{algorithm} run complete"]
            if payload.get("duration_seconds") is not None:
                conclusion_parts.append(f"{payload['duration_seconds']}s")
            conclusion = " \u00b7 ".join(conclusion_parts)
        elif status == manifest.STATUS_FAILED:
            conclusion = f"Run failed \u00b7 {payload.get('error') or 'no error recorded'}"
        else:
            conclusion = "Run cancelled."
        if self._conclusion.text():
            conclusion = f"{conclusion}\n{self._conclusion.text()}"
        self._conclusion.setText(conclusion)

        parameters = payload.get("parameters") or {}
        if parameters:
            lines.append(
                f"{parameters.get('method', 'fit_transform')} "
                "\u00b7 concentration workflow"
            )
        counts = payload.get("counts") or {}
        if counts:
            lines.append(
                f"{counts.get('samples')} samples \u00b7 "
                f"{counts.get('taxa')} taxa \u00b7 "
                f"{counts.get('batches')} batch(es)"
            )
        lines.extend(payload.get("notices") or [])
        lines.extend(payload.get("warnings") or [])
        self._notes.setPlainText("\n".join(lines))

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._run_dir)))

    def _open_log(self) -> None:
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self._run_dir / paths.BACKEND_STDOUT))
        )
