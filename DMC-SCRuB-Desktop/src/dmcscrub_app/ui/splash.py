"""The lab logo on white, shown while the main window is being built.

Deliberately not a `QSplashScreen`: that class paints its pixmap edge to edge and
draws its own text over it, and what is wanted here is the logo centred with a
white margin around it. A frameless top-level widget is the whole of it.

The delay is a floor, not a total. The window is constructed while the splash is
up, so on a slow machine the splash simply covers work that was going to happen
anyway; on a fast one it stays for the rest of the 1.5 seconds rather than
flashing past.
"""

from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

SPLASH_MS = 1500

_WINDOW = QSize(520, 300)
# Room around the logo, as a fraction of the window's width and height.
_MARGIN = 0.12


def _logo() -> QPixmap:
    path = files("dmcscrub_app.resources").joinpath("korem_lab_logo.png")
    return QPixmap(str(path))


class SplashScreen(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFixedSize(_WINDOW)
        self._logo = _logo()
        self._centre()

    def _centre(self) -> None:
        screen = self.screen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))
        if self._logo.isNull():
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        box = self.rect().adjusted(
            int(self.width() * _MARGIN),
            int(self.height() * _MARGIN),
            -int(self.width() * _MARGIN),
            -int(self.height() * _MARGIN),
        )
        scaled = self._logo.scaled(box.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap(
            box.x() + (box.width() - scaled.width()) // 2,
            box.y() + (box.height() - scaled.height()) // 2,
            scaled,
        )
