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
    QInputDialog,
    QPushButton,
    QTabBar,
    QTabWidget,
)

# Chrome-like tab sizing: shrink when crowded, but never below _MIN_TAB_W;
# never grow past _MAX_TAB_W. Space kept free at the end for the '+' button.
_MIN_TAB_W = 116
_MAX_TAB_W = 220
_ADD_BUTTON_SPACE = 44


class _DatasetTabBar(QTabBar):
    rename_requested = Signal(int)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        index = self.tabAt(event.position().toPoint())
        if index >= 0:
            self.rename_requested.emit(index)
        super().mouseDoubleClickEvent(event)

    def tabSizeHint(self, index: int) -> QSize:  # noqa: N802 (Qt override)
        # Do not call super().tabSizeHint() here. On PySide6 6.7 / Qt 6.7,
        # QTabWidget.addTab -> layoutTabs re-enters this override while the new
        # tab is only partially inserted, and super() SIGSEGVs inside
        # QTabBarPrivate::initBasicStyleOption. Compute a self-contained size.
        del index  # width is shared across tabs; index is unused on purpose
        count = self.count() or 1
        available = self.width() - _ADD_BUTTON_SPACE
        if available > 0:
            width = max(_MIN_TAB_W, min(_MAX_TAB_W, available // count))
        else:
            width = _MIN_TAB_W
        height = max(self.fontMetrics().height() + 12, 28)
        return QSize(width, height)


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
        # Defer tabRect-based layout until after addTab finishes. Calling
        # tabRect synchronously here can re-enter tabSizeHint mid-insert.
        QTimer.singleShot(0, self._reposition_add_button)

    def tabRemoved(self, index: int) -> None:  # noqa: N802 (Qt override)
        super().tabRemoved(index)
        QTimer.singleShot(0, self._reposition_add_button)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._reposition_add_button()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._schedule_reposition()

    # -- Close buttons -------------------------------------------------------
    def _install_close_button(self, index: int) -> None:
        # Install the close QPushButton directly. Wrapping it in a layout-bearing
        # QWidget container SIGSEGVs on PySide6/Qt 6.7 when QTabBar later computes
        # tabRect/layoutTabs (QTabBarPrivate::initBasicStyleOption). Inset is
        # handled by the tabCloseButton stylesheet instead of a host margin.
        button = QPushButton("\u2715")
        button.setObjectName("tabCloseButton")
        button.setFixedSize(15, 15)
        button.setToolTip("Close this tab")
        button.clicked.connect(lambda: self._close_from_button(button))
        self._bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, button)

    def _close_from_button(self, button: QPushButton) -> None:
        for index in range(self.count()):
            if self._bar.tabButton(index, QTabBar.ButtonPosition.RightSide) is button:
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
