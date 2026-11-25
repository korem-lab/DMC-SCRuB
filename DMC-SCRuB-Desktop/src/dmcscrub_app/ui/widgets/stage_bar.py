"""The four-segment stage strip: Load, Build inputs, Fit, Save.

Split out of `RunProgress` because the history detail page shows the same strip in
a finished state, and because it is the piece that answers "where is it now" at a
glance -- the progress bar alone cannot, since only the fit stage is measurable.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from dmcscrub_app.backend.contracts import (
    STAGE_BUILDING_INPUTS,
    STAGE_FITTING,
    STAGE_LOADING,
    STAGE_SAVING,
)

STAGE_LABELS: tuple[tuple[str, str], ...] = (
    (STAGE_LOADING, "Load"),
    (STAGE_BUILDING_INPUTS, "Build inputs"),
    (STAGE_FITTING, "Fit"),
    (STAGE_SAVING, "Save"),
)


class StageBar(QWidget):
    """States per segment: `done`, `active`, `pending`, styled from the sheet."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("stageBar")
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._segments: dict[str, QLabel] = {}
        for index, (stage, label) in enumerate(STAGE_LABELS):
            if index:
                arrow = QLabel("\u2192")
                arrow.setObjectName("stageArrow")
                layout.addWidget(arrow)
            segment = QLabel(label)
            segment.setObjectName("stageSegment")
            segment.setProperty("state", "pending")
            self._segments[stage] = segment
            layout.addWidget(segment)
        layout.addStretch(1)

    def set_current(self, stage: str | None) -> None:
        order = [name for name, _ in STAGE_LABELS]
        current = order.index(stage) if stage in order else -1
        for index, name in enumerate(order):
            if current < 0:
                state = "pending"
            elif index < current:
                state = "done"
            elif index == current:
                state = "active"
            else:
                state = "pending"
            self._apply(self._segments[name], state, done_prefix=state == "done")

    def set_all_done(self) -> None:
        for segment in self._segments.values():
            self._apply(segment, "done", done_prefix=True)

    def _apply(self, segment: QLabel, state: str, *, done_prefix: bool) -> None:
        base = segment.text().lstrip("\u2713 ")
        segment.setText(f"\u2713 {base}" if done_prefix else base)
        segment.setProperty("state", state)
        # Property-based styling only repaints after the style is re-evaluated.
        segment.style().unpolish(segment)
        segment.style().polish(segment)
