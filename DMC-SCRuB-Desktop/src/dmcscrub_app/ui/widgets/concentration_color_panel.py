"""Concentration legend, sample colours, and placeholder Run button."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from dmcscrub_app.ui.models import (
    ALGORITHM_C_SCRUB,
    ALGORITHM_DMC_SCRUB,
    ConcentrationEntry,
    PipelineVM,
)

_HIGH_COLOR = QColor("#c62828")
_LOW_COLOR = QColor("#2e7d32")


def _format_value(value: float) -> str:
    return f"{value:.6g}"


def _concentration_color(value: float, minimum: float, maximum: float) -> QColor:
    ratio = 0.5 if maximum == minimum else (value - minimum) / (maximum - minimum)
    ratio = max(0.0, min(1.0, ratio))
    red = round(_LOW_COLOR.red() + ratio * (_HIGH_COLOR.red() - _LOW_COLOR.red()))
    green = round(
        _LOW_COLOR.green() + ratio * (_HIGH_COLOR.green() - _LOW_COLOR.green())
    )
    blue = round(_LOW_COLOR.blue() + ratio * (_HIGH_COLOR.blue() - _LOW_COLOR.blue()))
    return QColor(red, green, blue)


class ConcentrationColorPanel(QWidget):
    run_clicked = Signal()
    changed = Signal()

    def __init__(self, concentrations: list[ConcentrationEntry]) -> None:
        super().__init__()
        self._read_only = False
        self._steps = []
        self.setObjectName("controlPanel")
        self.setProperty("panelType", "concentration")
        self.setAttribute(Qt.WA_StyledBackground, True)

        title = QLabel("Concentration Color Table")
        title.setObjectName("panelTitle")

        values = [entry.concentration for entry in concentrations]
        minimum = min(values, default=0.0)
        maximum = max(values, default=0.0)

        legend_bar = QFrame()
        legend_bar.setObjectName("concentrationLegendBar")
        legend_bar.setFixedHeight(18)
        legend_bar.setStyleSheet(
            "QFrame#concentrationLegendBar {"
            "border: 1px solid #9ca3af; border-radius: 5px;"
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            "stop:0 #c62828, stop:1 #2e7d32);"
            "}"
        )

        legend_labels = QHBoxLayout()
        legend_labels.setContentsMargins(0, 0, 0, 0)
        legend_labels.addWidget(QLabel(f"Max  {_format_value(maximum)}"))
        legend_labels.addStretch(1)
        legend_labels.addWidget(QLabel(f"Min  {_format_value(minimum)}"))

        table = QWidget()
        table_layout = QGridLayout(table)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setHorizontalSpacing(10)
        table_layout.setVerticalSpacing(7)
        for column, text in enumerate(("Sample", "Concentration", "Color")):
            header = QLabel(text)
            header.setObjectName("sectionHeading")
            table_layout.addWidget(header, 0, column)

        for row, entry in enumerate(concentrations, start=1):
            sample = QLabel(entry.sample_name)
            sample.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value = QLabel(_format_value(entry.concentration))
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            swatch = QFrame()
            swatch.setFixedSize(24, 18)
            swatch.setStyleSheet(
                "QFrame {"
                f"background: {_concentration_color(entry.concentration, minimum, maximum).name()};"
                "border: 1px solid #6b7280; border-radius: 4px;"
                "}"
            )
            table_layout.addWidget(sample, row, 0)
            table_layout.addWidget(value, row, 1)
            table_layout.addWidget(swatch, row, 2, alignment=Qt.AlignCenter)
        table_layout.setColumnStretch(0, 1)

        scroll = QScrollArea()
        scroll.setObjectName("concentrationScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(table)

        self._run_button = QPushButton("Run")
        self._run_button.setObjectName("concentrationRunButton")
        self._run_button.setMinimumHeight(42)
        self._run_button.clicked.connect(self.run_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(legend_bar)
        layout.addLayout(legend_labels)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._run_button)

    def set_pipeline(self, pipeline: PipelineVM) -> None:
        self._steps = list(pipeline.steps)

    def step_config(self) -> list[dict]:
        return [
            {
                "key": step.key,
                "control_groups": [],
                "in_dag": True,
                "in_decontamination": True,
            }
            for step in self._steps
        ]

    def apply_selections(self, selections: list[dict]) -> None:
        return

    def set_run_method(self, method: str) -> None:
        if method not in (ALGORITHM_C_SCRUB, ALGORITHM_DMC_SCRUB):
            raise ValueError(f"Unsupported concentration algorithm: {method!r}")
        self._run_button.setText(f"Run {method}")
        style_name = "cscrub" if method == ALGORITHM_C_SCRUB else "dmcscrub"
        self._run_button.setProperty("runAlgorithm", style_name)
        self._run_button.style().unpolish(self._run_button)
        self._run_button.style().polish(self._run_button)

    def set_running(self, running: bool) -> None:
        self._run_button.setEnabled(not running and not self._read_only)

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = read_only
        self._run_button.setVisible(not read_only)
        self._run_button.setEnabled(not read_only)
