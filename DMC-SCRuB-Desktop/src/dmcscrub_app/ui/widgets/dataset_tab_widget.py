"""Chrome-style tab widget: a '+' after the last tab, per-tab close, rename.

- The add button floats just past the last tab and follows tab layout changes.
- Each tab has a close button on the *right* side (custom, so it is not subject
  to the macOS default of placing close buttons on the left).
- Double-clicking a tab renames it in place.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QPushButton,
    QTabBar,
    QTabWidget,
    QWidget,
)

# Chrome-like tab sizing: shrink when crowded, but never below _MIN_TAB_W;
# never grow past _MAX_TAB_W. Space kept free at the end for the '+' button.
_MIN_TAB_W = 116
_MAX_TAB_W = 220
_ADD_BUTTON_SPACE = 44
# Fixed inset of the close glyph from the tab's right border (constant for any
# tab width). The close button lives inside a container with this right margin.
_CLOSE_RIGHT_INSET = 10


class _DatasetTabBar(QTabBar):
    rename_requested = Signal(int)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        index = self.tabAt(event.position().toPoint())
        if index >= 0:
            self.rename_requested.emit(index)
        super().mouseDoubleClickEvent(event)

    def tabSizeHint(self, index: int) -> QSize:  # noqa: N802 (Qt override)
        size = super().tabSizeHint(index)
        count = self.count() or 1
        available = self.width() - _ADD_BUTTON_SPACE
        if available > 0:
            ideal = available // count
            width = max(_MIN_TAB_W, min(_MAX_TAB_W, ideal))
        else:
            width = max(_MIN_TAB_W, min(_MAX_TAB_W, size.width()))
        size.setWidth(width)
        return size


class DatasetTabWidget(QTabWidget):
    add_requested = Signal()
    dataset_renamed = Signal(int, str)

    def __init__(self) -> None:
        super().__init__()
        self._bar = _DatasetTabBar()
        self.setTabBar(self._bar)
        self.setDocumentMode(True)
        self.setMovable(True)
        # We manage our own right-side close buttons instead of the built-in
        # ones (which macOS renders on the left).
        self.setTabsClosable(False)
        # Chrome-like behaviour: tabs shrink to fit (down to a minimum) and long
        # titles elide, rather than the whole bar overflowing at full width.
        self._bar.setExpanding(False)
        self.setElideMode(Qt.TextElideMode.ElideRight)

        self._add_button = QPushButton("+", self._bar)
        self._add_button.setObjectName("tabAddButton")
        self._add_button.setToolTip("Add a new dataset tab")
        self._add_button.setFixedSize(28, 24)
        self._add_button.clicked.connect(self.add_requested)

        self._bar.rename_requested.connect(self._rename_tab)
        self._bar.tabMoved.connect(lambda *_: self._reposition_add_button())
        self._schedule_reposition()

    def add_button_popup_pos(self) -> QPoint:
        """Global point just under the '+' so a menu can open there."""
        return self._add_button.mapToGlobal(QPoint(0, self._add_button.height()))

    # -- Qt overrides --------------------------------------------------------
    def tabInserted(self, index: int) -> None:  # noqa: N802 (Qt override)
        super().tabInserted(index)
        self._install_close_button(index)
        self._schedule_reposition()

    def tabRemoved(self, index: int) -> None:  # noqa: N802 (Qt override)
        super().tabRemoved(index)
        self._schedule_reposition()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._reposition_add_button()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._schedule_reposition()

    # -- Close buttons -------------------------------------------------------
    def _install_close_button(self, index: int) -> None:
        # The button lives inside a transparent container whose right margin
        # gives the glyph a constant inset from the tab's right border. Qt pins
        # the container to the right edge, so the inset and button size stay
        # fixed no matter how wide/narrow the tab gets.
        button = QPushButton("\u2715")
        button.setObjectName("tabCloseButton")
        button.setFixedSize(15, 15)
        button.setToolTip("Close this tab")
        button.clicked.connect(lambda: self._close_from_button(button))

        container = QWidget()
        container.setObjectName("tabCloseHost")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, _CLOSE_RIGHT_INSET, 0)
        layout.setSpacing(0)
        layout.addWidget(button)

        self._bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, container)

    def _close_from_button(self, button: QPushButton) -> None:
        container = button.parentWidget()
        for index in range(self.count()):
            if self._bar.tabButton(index, QTabBar.ButtonPosition.RightSide) is container:
                self.tabCloseRequested.emit(index)
                return

    # -- Add button positioning ---------------------------------------------
    def _schedule_reposition(self) -> None:
        # tabRect is not final on the very first insert; reposition once the
        # layout settles as well, otherwise the '+' starts in the wrong place.
        self._reposition_add_button()
        QTimer.singleShot(0, self._reposition_add_button)

    def _reposition_add_button(self) -> None:
        count = self._bar.count()
        if count == 0:
            x = 6
            height = self._add_button.height()
        else:
            last_rect = self._bar.tabRect(count - 1)
            x = last_rect.right() + 6
            height = last_rect.height()
        y = max((height - self._add_button.height()) // 2, 0)
        self._add_button.move(x, y)
        self._add_button.raise_()
        self._add_button.show()

    # -- Rename --------------------------------------------------------------
    def _rename_tab(self, index: int) -> None:
        current = self.tabText(index)
        text, ok = QInputDialog.getText(self, "Rename Dataset", "Dataset name:", text=current)
        if ok and text.strip():
            name = text.strip()
            self.setTabText(index, name)
            self.dataset_renamed.emit(index, name)
