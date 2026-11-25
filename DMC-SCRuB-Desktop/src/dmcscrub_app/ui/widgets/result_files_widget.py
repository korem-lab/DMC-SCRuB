"""Download entry point for a run directory.

Knows exactly two things: how to zip a directory, and how to save one file out of
it. It never learns how the run was produced, which is what lets the live result
panel and a history detail page use the same widget.

The user-facing scientific outputs live behind one dropdown. Reproducibility
metadata and logs stay in ``run_details`` and are included only by Save all.
"""

from __future__ import annotations

import errno
import shutil
import zipfile
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QLayout,
    QLayoutItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from dmcscrub_app.backend import paths


class _ResponsiveButtonLayout(QLayout):
    """Arrange four actions as 4x1, 2x2, or 1x4 based on available width."""

    def __init__(self) -> None:
        super().__init__()
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(8)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 (Qt override)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 (Qt override)
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 (Qt override)
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802 (Qt override)
        return Qt.Horizontal

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt override)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt override)
        left, top, right, bottom = self.getContentsMargins()
        available = max(0, width - left - right)
        columns = self._columns_for_width(available)
        _, row_heights = self._grid_metrics(columns)
        rows_height = sum(row_heights) + self.spacing() * max(0, len(row_heights) - 1)
        return top + rows_height + bottom

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 (Qt override)
        super().setGeometry(rect)
        left, top, right, bottom = self.getContentsMargins()
        content = rect.adjusted(left, top, -right, -bottom)
        columns = self._columns_for_width(content.width())
        column_widths, row_heights = self._grid_metrics(columns)

        x_positions: list[int] = []
        x = content.x()
        for width in column_widths:
            x_positions.append(x)
            x += width + self.spacing()

        y_positions: list[int] = []
        y = content.y()
        for height in row_heights:
            y_positions.append(y)
            y += height + self.spacing()

        for index, item in enumerate(self._items):
            row, column = divmod(index, columns)
            item.setGeometry(
                QRect(
                    x_positions[column],
                    y_positions[row],
                    column_widths[column],
                    row_heights[row],
                )
            )

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        if not self._items:
            return QSize()
        columns = len(self._items)
        column_widths, row_heights = self._grid_metrics(columns)
        left, top, right, bottom = self.getContentsMargins()
        return QSize(
            left + sum(column_widths) + self.spacing() * (columns - 1) + right,
            top + max(row_heights, default=0) + bottom,
        )

    def minimumSize(self) -> QSize:  # noqa: N802 (Qt override)
        if not self._items:
            return QSize()
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size + QSize(left + right, top + bottom)

    def _columns_for_width(self, width: int) -> int:
        count = len(self._items)
        if count <= 1:
            return max(1, count)
        if width >= self._required_width(count):
            return count
        if count >= 4 and width >= self._required_width(2):
            return 2
        return 1

    def _required_width(self, columns: int) -> int:
        column_widths, _ = self._grid_metrics(columns)
        return sum(column_widths) + self.spacing() * max(0, columns - 1)

    def _grid_metrics(self, columns: int) -> tuple[list[int], list[int]]:
        columns = max(1, columns)
        rows = (len(self._items) + columns - 1) // columns
        column_widths = [0] * columns
        row_heights = [0] * rows
        for index, item in enumerate(self._items):
            size = item.sizeHint()
            row, column = divmod(index, columns)
            column_widths[column] = max(column_widths[column], size.width())
            row_heights[row] = max(row_heights[row], size.height())
        return column_widths, row_heights


class ResultFilesWidget(QWidget):
    """`Save all (.zip)` plus a menu of user-facing scientific outputs."""

    def __init__(self) -> None:
        super().__init__()
        self._run_dir: Path | None = None

        self._zip_button = QPushButton("Save all (.zip)")
        self._zip_button.setObjectName("primaryButton")
        self._zip_button.clicked.connect(self._save_zip)

        self._file_button = QPushButton("Save file \u25be")
        self._file_button.clicked.connect(self._show_menu)

        self._button_layout = _ResponsiveButtonLayout()
        self.setLayout(self._button_layout)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._button_layout.addWidget(self._zip_button)
        self._button_layout.addWidget(self._file_button)

        self.set_run_dir(None)

    def add_action_button(self, button: QPushButton) -> None:
        """Add a non-download result action to the same responsive button group."""
        self._button_layout.addWidget(button)
        self.updateGeometry()

    def set_run_dir(self, run_dir: Path | None) -> None:
        self._run_dir = run_dir
        enabled = run_dir is not None and run_dir.is_dir()
        self._zip_button.setEnabled(enabled)
        self._file_button.setEnabled(enabled)

    def _show_menu(self) -> None:
        if self._run_dir is None:
            return
        menu = QMenu(self)
        for label, source in self._available_download_items():
            menu.addAction(label, lambda p=source: self._save_file(p))
        menu.exec(self._file_button.mapToGlobal(self._file_button.rect().bottomLeft()))

    def _available_download_items(self) -> list[tuple[str, Path]]:
        if self._run_dir is None:
            return []
        return [
            (label, self._run_dir / filename)
            for label, filename in paths.DOWNLOAD_ITEMS
            if (self._run_dir / filename).is_file()
        ]

    def _save_zip(self) -> None:
        if self._run_dir is None:
            return
        suggested = f"{self._run_dir.name}.zip"
        target, _ = QFileDialog.getSaveFileName(
            self, "Save all results", suggested, "Zip archive (*.zip)"
        )
        if not target:
            return
        try:
            self._write_zip(Path(target))
        except OSError as exc:
            QMessageBox.critical(self, "Could Not Save", _save_error_message(exc))

    def _write_zip(self, target: Path) -> None:
        """Everything in the directory, so the archive can retell the whole run."""
        run_dir = self._run_dir
        assert run_dir is not None
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for entry in sorted(run_dir.rglob("*")):
                if entry.is_file():
                    archive.write(entry, entry.relative_to(run_dir.parent))

    def _save_file(self, source: Path) -> None:
        if not source.exists():
            QMessageBox.warning(
                self, "File Missing", f"{source.name} is not in this run folder."
            )
            return

        filters = (
            f"{source.suffix.lstrip('.').upper() or 'File'} (*{source.suffix});;"
            "All files (*)"
        )
        target_name, _ = QFileDialog.getSaveFileName(
            self,
            "Save file",
            source.name,
            filters,
        )
        if not target_name:
            return

        target = Path(target_name)
        try:
            shutil.copyfile(source, target)
        except OSError as exc:
            QMessageBox.critical(self, "Could Not Save", _save_error_message(exc))


def _save_error_message(exc: OSError) -> str:
    if exc.errno in (errno.ENOSPC, errno.EDQUOT):
        return (
            "Your computer does not have enough disk space. "
            "Please free up space and try again."
        )
    return str(exc)
