"""History list tab: one row per run directory, newest first.

Holds only `RunSummary` objects -- a few hundred bytes each, no tables. A result
table is read exactly once, at the moment the user clicks a download, and handed
straight to the filesystem. That is what keeps a hundred runs from filling memory.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from dmcscrub_app.backend import history, manifest

STATUS_TEXT = {
    manifest.STATUS_SUCCESS: "Success",
    manifest.STATUS_FAILED: "Failed",
    manifest.STATUS_CANCELLED: "Cancelled",
}


class _RunRow(QFrame):
    """One run. Clickable only when there is something to open."""

    clicked = Signal(object)
    selection_changed = Signal()

    def __init__(self, summary: history.RunSummary) -> None:
        super().__init__()
        self.setObjectName("historyRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.summary = summary

        self.checkbox = QCheckBox()
        self.checkbox.setVisible(False)
        self.checkbox.toggled.connect(self.selection_changed)

        name = QLabel(summary.dataset_name)
        name.setObjectName("historyName")

        badge = QLabel(STATUS_TEXT.get(summary.status, summary.status))
        badge.setObjectName("historyBadge")
        badge.setProperty("status", summary.status)

        detail = QLabel(self._detail_text(summary))
        detail.setObjectName("metricLabel")

        size = QLabel(history.format_size(summary.size_bytes))
        size.setObjectName("metricLabel")

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.checkbox)
        top.addWidget(name, 1)
        top.addWidget(badge)
        top.addWidget(size)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addWidget(detail)

        if summary.can_open_details:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Open this run")
        else:
            # A cancelled run has nothing to show, so an inert row is kinder than a
            # detail page of empty panels.
            self.setToolTip("This run was cancelled and has no details.")

    @staticmethod
    def _detail_text(summary: history.RunSummary) -> str:
        parts = [summary.created_at.replace("T", " "), summary.algorithm]
        if summary.samples is not None:
            parts.append(f"{summary.samples} samples")
        if summary.duration_seconds is not None:
            parts.append(f"{summary.duration_seconds:g}s")
        if summary.warning_count:
            parts.append(f"{summary.warning_count} warnings")
        if summary.error:
            parts.append(summary.error[:80])
        return "  \u00b7  ".join(parts)

    def set_select_mode(self, enabled: bool) -> None:
        self.checkbox.setVisible(enabled)
        if not enabled:
            self.checkbox.setChecked(False)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self.checkbox.isVisible():
            self.checkbox.toggle()
        elif self.summary.can_open_details:
            self.clicked.emit(self.summary)
        super().mouseReleaseEvent(event)


class HistoryView(QWidget):
    """The list, its selection mode, and the two delete actions."""

    run_opened = Signal(object)
    runs_deleted = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("historyView")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._rows: list[_RunRow] = []
        self._select_mode = False
        # Supplied by MainWindow. The active run has a directory but no manifest
        # yet, so it never appears in the list; this is the second line of defence.
        self._active_run_dir: Path | None = None

        title = QLabel("Run History")
        title.setObjectName("panelTitle")

        self._empty = QLabel("No runs yet. Results appear here after a run completes.")
        self._empty.setObjectName("emptyState")
        self._empty.setAlignment(Qt.AlignCenter)

        self._list_host = QWidget()
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("historyScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._list_host)

        self._total_label = QLabel("")
        self._total_label.setObjectName("metricLabel")

        self._delete_button = QPushButton("Delete")
        self._delete_button.clicked.connect(self._on_delete_clicked)
        self._clear_button = QPushButton("Clear")
        self._clear_button.clicked.connect(self._on_clear_clicked)
        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.clicked.connect(lambda: self._set_select_mode(False))
        self._cancel_button.setVisible(False)

        footer = QHBoxLayout()
        footer.addWidget(self._total_label, 1)
        footer.addWidget(self._delete_button)
        footer.addWidget(self._clear_button)
        footer.addWidget(self._cancel_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(self._empty)
        layout.addWidget(scroll, 1)
        layout.addLayout(footer)

        self.refresh()

    def set_active_run_dir(self, run_dir: Path | None) -> None:
        self._active_run_dir = run_dir

    def refresh(self) -> None:
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows = []

        summaries = history.list_runs()
        for summary in summaries:
            row = _RunRow(summary)
            row.clicked.connect(self.run_opened)
            row.selection_changed.connect(self._update_buttons)
            row.set_select_mode(self._select_mode)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)
            self._rows.append(row)

        self._empty.setVisible(not summaries)
        self._total_label.setText(
            f"{len(summaries)} runs \u00b7 {history.format_size(history.total_size_bytes())} on disk"
        )
        self._update_buttons()

    # --- deletion -----------------------------------------------------------

    def _set_select_mode(self, enabled: bool) -> None:
        self._select_mode = enabled
        for row in self._rows:
            row.set_select_mode(enabled)
        self._cancel_button.setVisible(enabled)
        self._clear_button.setVisible(not enabled)
        self._update_buttons()

    def _update_buttons(self) -> None:
        selected = sum(1 for row in self._rows if row.is_checked())
        if self._select_mode:
            self._delete_button.setText(f"Delete ({selected})" if selected else "Delete")
            self._delete_button.setEnabled(bool(selected))
        else:
            self._delete_button.setText("Delete")
            self._delete_button.setEnabled(bool(self._rows))
        self._clear_button.setEnabled(bool(self._rows))

    def _on_delete_clicked(self) -> None:
        # Browsing mode has no checkboxes at all, so a stray click cannot delete.
        if not self._select_mode:
            self._set_select_mode(True)
            return
        chosen = [row.summary for row in self._rows if row.is_checked()]
        if chosen and self._confirm(chosen):
            self._delete(chosen)
            self._set_select_mode(False)

    def _on_clear_clicked(self) -> None:
        # "Everything in this list", not "everything in the runs folder": the
        # active run's directory exists but is not listed, and rmtree on the root
        # would delete it mid-write.
        chosen = [row.summary for row in self._rows]
        if chosen and self._confirm(chosen):
            self._delete(chosen)

    def _confirm(self, chosen: list[history.RunSummary]) -> bool:
        freed = history.format_size(sum(item.size_bytes for item in chosen))
        box = QMessageBox(self)
        box.setWindowTitle("Delete Runs")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"Delete {len(chosen)} run(s) and free about {freed}?")
        box.setInformativeText("This cannot be undone.")
        box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
        box.setDefaultButton(QMessageBox.Cancel)
        return box.exec() == QMessageBox.Yes

    def _delete(self, chosen: list[history.RunSummary]) -> None:
        run_dirs = [item.run_dir for item in chosen]
        failures = history.delete_runs(run_dirs, exclude=self._active_run_dir)
        deleted = [path for path in run_dirs if not path.exists()]
        # Detail tabs pointing at a deleted directory would fail on any download.
        self.runs_deleted.emit(deleted)
        self.refresh()
        if failures:
            listed = "\n".join(f"{path.name}: {reason}" for path, reason in failures)
            QMessageBox.warning(self, "Some Runs Were Not Deleted", listed)
