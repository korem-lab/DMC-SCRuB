"""Result panel: stage strip, progress bar, detail line, downloads.

An explicit state machine. Each state sets every control in one go rather than
patching what changed, because the alternative -- incremental updates -- is how a
panel ends up showing a full progress bar while the stage strip still says Fit.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from dmcscrub_app.backend import paths
from dmcscrub_app.backend.contracts import (
    ALGORITHM_C_SCRUB,
    STAGE_BUILDING_INPUTS,
    STAGE_FITTING,
    STAGE_LOADING,
    STAGE_SAVING,
)
from dmcscrub_app.ui.widgets.result_files_widget import ResultFilesWidget
from dmcscrub_app.ui.widgets.stage_bar import StageBar

STATE_IDLE = "idle"
STATE_FINISHED = "finished"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"

class RunProgress(QFrame):
    """Owns nothing about the run; it is told what to display."""

    cancel_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("progressFrame")

        self._state = STATE_IDLE
        self._algorithm = ALGORITHM_C_SCRUB
        self._run_dir: Path | None = None
        self._started_at = 0.0

        self._title = QLabel("Result")
        self._title.setObjectName("panelTitle")

        self._stage_bar = StageBar()

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)

        self._detail = QLabel("Not started. Configure controls and click Run.")
        self._detail.setObjectName("metricLabel")
        self._detail.setWordWrap(True)

        self._notes = QTextEdit()
        self._notes.setObjectName("runNotes")
        self._notes.setReadOnly(True)
        self._notes.setMaximumHeight(96)
        self._notes.setPlaceholderText("Run notes will appear here.")

        self._open_folder = QPushButton("Open folder")
        self._open_folder.clicked.connect(self._on_open_folder)
        self._open_log = QPushButton("Open log")
        self._open_log.clicked.connect(self._on_open_log)
        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.clicked.connect(self.cancel_clicked)
        self.result_files = ResultFilesWidget()
        self.result_files.add_action_button(self._open_folder)
        self.result_files.add_action_button(self._open_log)

        cancel_row = QHBoxLayout()
        cancel_row.addStretch(1)
        cancel_row.addWidget(self._cancel_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addWidget(self._stage_bar)
        layout.addWidget(self._bar)
        layout.addWidget(self._detail)
        layout.addWidget(self._notes)
        layout.addWidget(self.result_files)
        layout.addLayout(cancel_row)

        # Elapsed time is driven by its own clock rather than by iteration events,
        # so it keeps moving even when a single iteration takes half a minute --
        # that is how the user can tell the program has not died.
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._refresh_detail)

        self.reset()
        self.hide()

    # --- lifecycle ----------------------------------------------------------

    def reset(self) -> None:
        self._state = STATE_IDLE
        self._run_dir = None
        self._elapsed_timer.stop()
        self._stage_bar.set_current(None)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._detail.setProperty("severity", "normal")
        self._repolish(self._detail)
        self._detail.setText("Not started. Check the inputs and click Run.")
        self._notes.clear()
        self.result_files.set_run_dir(None)
        self._open_folder.setEnabled(False)
        self._open_log.setEnabled(False)
        self._cancel_button.setEnabled(False)

    def start(
        self,
        run_dir: Path,
        *,
        algorithm: str = ALGORITHM_C_SCRUB,
    ) -> None:
        self.reset()
        self._run_dir = run_dir
        self._algorithm = algorithm
        self._started_at = time.monotonic()
        self._open_folder.setEnabled(True)
        self._open_log.setEnabled(True)
        self._cancel_button.setEnabled(True)
        self._bar.setRange(0, 0)  # indeterminate until the fit begins
        self.set_stage(STAGE_LOADING)
        self._elapsed_timer.start()
        self.show()

    def set_stage(self, stage: str) -> None:
        if self._state in (STATE_FINISHED, STATE_FAILED, STATE_CANCELLED):
            return
        self._state = stage
        self._stage_bar.set_current(stage)
        if stage == STATE_IDLE:
            return
        self._bar.setRange(0, 0)
        self._bar.setFormat("")
        self._refresh_detail()

    def set_input_summary(self, samples: int) -> None:
        self._input_summary = (
            f"Preparing {self._algorithm} \u2014 {samples} aligned samples"
        )
        if self._state == STAGE_BUILDING_INPUTS:
            self._refresh_detail()

    def finish(self, run_dir: Path) -> None:
        self._state = STATE_FINISHED
        self._run_dir = run_dir
        self._elapsed_timer.stop()
        self._stage_bar.set_all_done()
        self._bar.setRange(0, 100)
        self._bar.setValue(100)
        self._bar.setFormat("")
        self._set_detail(
            f"{self._algorithm} run complete \u00b7 {self._elapsed_text()}",
            "success",
        )
        self.result_files.set_run_dir(run_dir)
        self._cancel_button.setEnabled(False)

    def fail(self, message: str) -> None:
        self._state = STATE_FAILED
        self._elapsed_timer.stop()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFormat("")
        self._set_detail(message, "error")
        # No result download: there are no results. The log is what helps here.
        self.result_files.set_run_dir(None)
        self._cancel_button.setEnabled(False)

    def cancel(self) -> None:
        self._state = STATE_CANCELLED
        self._elapsed_timer.stop()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFormat("")
        self._set_detail("Cancelled.", "normal")
        self.result_files.set_run_dir(None)
        self._cancel_button.setEnabled(False)

    # --- run notes ----------------------------------------------------------

    def add_note(self, text: str) -> None:
        self._notes.append(text)

    def set_notes(self, lines: list[str]) -> None:
        self._notes.setPlainText("\n".join(lines))

    # --- detail line --------------------------------------------------------

    def _refresh_detail(self) -> None:
        if self._state == STAGE_LOADING:
            self._set_detail("Reading count and metadata tables\u2026", "normal")
        elif self._state == STAGE_BUILDING_INPUTS:
            self._set_detail(getattr(self, "_input_summary", "Preparing inputs\u2026"), "normal")
        elif self._state == STAGE_FITTING:
            self._set_detail(
                f"Running {self._algorithm} \u00b7 elapsed {self._elapsed_text()}",
                "normal",
            )
        elif self._state == STAGE_SAVING:
            self._set_detail("Writing results\u2026", "normal")

    def _elapsed_text(self) -> str:
        return self._duration_text(time.monotonic() - self._started_at)

    @staticmethod
    def _duration_text(seconds: float) -> str:
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def _set_detail(self, text: str, severity: str) -> None:
        self._detail.setText(text)
        self._detail.setProperty("severity", severity)
        self._repolish(self._detail)

    @staticmethod
    def _repolish(widget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    # --- actions ------------------------------------------------------------

    def _on_open_folder(self) -> None:
        if self._run_dir is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._run_dir)))

    def _on_open_log(self) -> None:
        if self._run_dir is not None:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self._run_dir / paths.BACKEND_STDOUT))
            )
