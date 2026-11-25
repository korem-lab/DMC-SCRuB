from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QGroupBox, QLabel, QPushButton


class FilePicker(QGroupBox):
    path_changed = Signal(str)

    def __init__(self, label: str, button_text: str = "Choose CSV") -> None:
        super().__init__(label)
        self._path: Path | None = None

        self.path_label = QLabel("No file selected")
        self.path_label.setObjectName("pathLabel")
        self.button = QPushButton(button_text)
        self.button.clicked.connect(self._choose_file)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(self.path_label, 1)
        layout.addWidget(self.button)

    @property
    def path(self) -> Path | None:
        return self._path

    def _choose_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Choose CSV", "", "CSV files (*.csv);;All files (*)")
        if not file_path:
            return

        self._path = Path(file_path)
        self.path_label.setText(str(self._path))
        self.path_changed.emit(str(self._path))
