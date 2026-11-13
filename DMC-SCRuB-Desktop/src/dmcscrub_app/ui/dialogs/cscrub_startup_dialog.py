"""Upload dialog shared by the C-SCRuB algorithm family."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from dmcscrub_app.ui.data_provider import DatasetProvider
from dmcscrub_app.ui.metadata_error_messages import metadata_error_message
from dmcscrub_app.ui.models import (
    ALGORITHM_DMC_SCRUB,
    ColumnMapping,
    DatasetConfig,
)
from dmcscrub_app.ui.widgets.file_picker import FilePicker


class CScrubStartupDialog(QDialog):
    """Upload UI shared by C-SCRuB and DMC-SCRuB."""

    def __init__(
        self,
        provider: DatasetProvider,
        algorithm: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider = provider
        self._algorithm = algorithm
        self._is_dmc = algorithm == ALGORITHM_DMC_SCRUB
        self.setWindowTitle(f"New {algorithm} Dataset")
        self.setModal(True)
        self.setMinimumWidth(560)

        title = QLabel(f"Load a {algorithm} dataset")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Select input tables and map the required metadata columns.")
        subtitle.setObjectName("dialogSubtitle")

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Dataset name (used as the tab title)")

        self.count_picker = FilePicker("Sample / Count Table")
        self.metadata_picker = FilePicker("Metadata Table")

        self.sample_combo = QComboBox()
        self.concentration_combo = QComboBox()
        self.batch_combo = QComboBox() if self._is_dmc else None
        self.label_combo = QComboBox() if self._is_dmc else None
        self.positive_value_combo = QComboBox() if self._is_dmc else None
        for combo in self._column_combos():
            combo.setEnabled(False)
        if self.positive_value_combo is not None:
            self.positive_value_combo.setPlaceholderText(
                "Select the value treated as 1"
            )
            self.positive_value_combo.setEnabled(False)

        columns_box = QGroupBox("Column Mapping")
        columns_form = QFormLayout(columns_box)
        columns_form.addRow("Sample name column", self.sample_combo)
        columns_form.addRow("Concentration column", self.concentration_combo)
        if self.batch_combo is not None:
            columns_form.addRow("Batch column", self.batch_combo)
            columns_form.addRow("Label column", self.label_combo)
            columns_form.addRow(
                "Positive value",
                self.positive_value_combo,
            )

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.button(QDialogButtonBox.Ok).setText("Open Dataset")
        self.button_box.button(QDialogButtonBox.Ok).setObjectName("primaryButton")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.name_edit)
        layout.addWidget(self.count_picker)
        layout.addWidget(self.metadata_picker)
        layout.addWidget(columns_box)
        layout.addWidget(self.button_box)

        self.count_picker.path_changed.connect(self._on_count_changed)
        self.metadata_picker.path_changed.connect(self._on_metadata_changed)
        self.button_box.accepted.connect(self._validate_and_accept)
        self.button_box.rejected.connect(self.reject)
        for combo in self._required_combos():
            combo.currentTextChanged.connect(lambda _text: self._refresh_ok_state())
        if self.label_combo is not None:
            self.label_combo.currentTextChanged.connect(
                self._on_label_column_changed
            )

        self._refresh_ok_state()

    def dataset_config(self) -> DatasetConfig:
        if self.count_picker.path is None or self.metadata_picker.path is None:
            raise ValueError("Both input files must be selected before opening the dataset.")
        name = self.name_edit.text().strip() or self.count_picker.path.stem
        return DatasetConfig(
            name=name,
            count_path=self.count_picker.path,
            metadata_path=self.metadata_picker.path,
            mapping=ColumnMapping(
                sample=self.sample_combo.currentText(),
                concentration=self.concentration_combo.currentText(),
                batch=self.batch_combo.currentText() if self.batch_combo is not None else "",
                label=self.label_combo.currentText() if self.label_combo is not None else "",
                positive_value=(
                    self.positive_value_combo.currentText()
                    if self.positive_value_combo is not None
                    else ""
                ),
            ),
            algorithm=self._algorithm,
        )

    def _on_count_changed(self, path: str) -> None:
        if not self.name_edit.text().strip():
            self.name_edit.setText(Path(path).stem)
        if self._input_paths_are_same():
            self._warn_same_input_file()
        self._refresh_ok_state()

    def _on_metadata_changed(self, path: str) -> None:
        self._reset_column_mapping()
        metadata_path = Path(path)
        if self._input_paths_are_same():
            self._warn_same_input_file()
            return
        try:
            columns = self._provider.read_metadata_columns(metadata_path)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Invalid CSV File",
                metadata_error_message(exc),
            )
            return
        for combo in self._column_combos():
            combo.blockSignals(True)
            combo.addItems(columns)
            combo.setEnabled(bool(columns))
            combo.blockSignals(False)
        if self.sample_combo.count() > 0:
            self.sample_combo.setCurrentIndex(0)
        if self.concentration_combo.count() > 1:
            self.concentration_combo.setCurrentIndex(1)
        if self.batch_combo is not None and self.batch_combo.count() > 2:
            self.batch_combo.setCurrentIndex(2)
        if self.label_combo is not None:
            self.label_combo.setCurrentIndex(-1)
        self._reset_positive_values()
        self._refresh_ok_state()

    def _reset_column_mapping(self) -> None:
        for combo in self._column_combos():
            combo.blockSignals(True)
            combo.clear()
            combo.setEnabled(False)
            combo.blockSignals(False)
        self._reset_positive_values()
        self._refresh_ok_state()

    def _on_label_column_changed(self, column: str) -> None:
        self._reset_positive_values()
        metadata_path = self.metadata_picker.path
        if (
            self.positive_value_combo is None
            or metadata_path is None
            or not column
        ):
            self._refresh_ok_state()
            return
        try:
            values = self._provider.read_metadata_values(metadata_path, column)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Invalid Metadata Column",
                metadata_error_message(exc),
            )
            self._refresh_ok_state()
            return

        self.positive_value_combo.blockSignals(True)
        self.positive_value_combo.addItems(values)
        self.positive_value_combo.setEnabled(bool(values))
        self.positive_value_combo.setCurrentIndex(0 if values else -1)
        self.positive_value_combo.blockSignals(False)
        self._refresh_ok_state()

    def _reset_positive_values(self) -> None:
        if self.positive_value_combo is None:
            return
        self.positive_value_combo.blockSignals(True)
        self.positive_value_combo.clear()
        self.positive_value_combo.setEnabled(False)
        self.positive_value_combo.blockSignals(False)

    def _refresh_ok_state(self) -> None:
        ready = (
            self.count_picker.path is not None
            and self.metadata_picker.path is not None
            and not self._input_paths_are_same()
            and all(combo.currentText() for combo in self._required_combos())
        )
        self.button_box.button(QDialogButtonBox.Ok).setEnabled(ready)

    def _validate_and_accept(self) -> None:
        count_path = self.count_picker.path
        metadata_path = self.metadata_picker.path
        if count_path is None or metadata_path is None:
            QMessageBox.warning(
                self,
                "Input Files",
                "Both input files must be selected before opening the dataset.",
            )
            return
        if not count_path.is_file():
            QMessageBox.warning(
                self,
                "Input Files",
                f"The selected Count file no longer exists: {count_path}. "
                "Please reselect the file.",
            )
            return
        if not metadata_path.is_file():
            QMessageBox.warning(
                self,
                "Input Files",
                f"The selected Metadata file no longer exists: {metadata_path}. "
                "Please reselect the file.",
            )
            return
        if self._input_paths_are_same():
            self._warn_same_input_file()
            return
        columns = [combo.currentText() for combo in self._column_combos()]
        if len(set(columns)) != len(columns):
            column_names = (
                "Sample name, concentration, batch, and label"
                if self.batch_combo is not None
                else "Sample name and concentration"
            )
            QMessageBox.warning(
                self,
                "Column Mapping",
                f"{column_names} must use different columns.",
            )
            return
        self.accept()

    def _input_paths_are_same(self) -> bool:
        count_path = self.count_picker.path
        metadata_path = self.metadata_picker.path
        if count_path is None or metadata_path is None:
            return False
        if count_path.exists() and metadata_path.exists():
            return os.path.samefile(count_path, metadata_path)
        return count_path.resolve() == metadata_path.resolve()

    def _warn_same_input_file(self) -> None:
        QMessageBox.warning(
            self,
            "Input Files",
            "Sample / Count Table and Metadata Table must be different files.",
        )

    def _column_combos(self) -> tuple[QComboBox, ...]:
        if (
            self.batch_combo is None
            or self.label_combo is None
        ):
            return (self.sample_combo, self.concentration_combo)
        return (
            self.sample_combo,
            self.concentration_combo,
            self.batch_combo,
            self.label_combo,
        )

    def _required_combos(self) -> tuple[QComboBox, ...]:
        if self.positive_value_combo is None:
            return self._column_combos()
        return (*self._column_combos(), self.positive_value_combo)
