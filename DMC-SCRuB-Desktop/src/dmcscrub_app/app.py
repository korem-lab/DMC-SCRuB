from __future__ import annotations

from importlib.resources import files
import sys
import traceback
import types

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from dmcscrub_app.ui.data_provider import RealDatasetProvider
from dmcscrub_app.ui.main_window import MainWindow
from dmcscrub_app.ui.splash import SPLASH_MS, SplashScreen


def _install_excepthook() -> None:
    """Surface uncaught exceptions as a dialog instead of aborting the app.

    PySide6 terminates the process on an unhandled exception raised inside a
    Qt slot. Catching it here keeps the window alive and shows what went wrong.
    """

    def handle(exc_type: type[BaseException], exc: BaseException, tb: types.TracebackType | None) -> None:
        message = "".join(traceback.format_exception(exc_type, exc, tb))
        sys.stderr.write(message)
        try:
            QMessageBox.critical(None, "Unexpected Error", message)
        except Exception:
            pass

    sys.excepthook = handle


def create_app(argv: list[str] | None = None) -> QApplication:
    app = QApplication(argv or sys.argv)
    app.setApplicationName("DMC-SCRuB DESKTOP")
    app.setWindowIcon(
        QIcon(str(files("dmcscrub_app.resources").joinpath("korem_lab_logo.png")))
    )

    style_path = files("dmcscrub_app.resources").joinpath("styles.qss")
    chevron_path = files("dmcscrub_app.resources").joinpath("chevron_down.svg")
    check_path = files("dmcscrub_app.resources").joinpath("check.svg")
    stylesheet = (
        style_path.read_text(encoding="utf-8")
        .replace("__CHEVRON_DOWN_SVG__", str(chevron_path))
        .replace("__CHECK_SVG__", str(check_path))
    )
    app.setStyleSheet(stylesheet)
    return app


def run() -> int:
    _install_excepthook()
    app = create_app()
    app.setQuitOnLastWindowClosed(True)

    splash = SplashScreen()
    splash.show()
    # The splash is painted before the window is built, not after: constructing
    # MainWindow reads the run history off disk, and without this the first thing
    # the user sees would be an unpainted white rectangle.
    app.processEvents()

    window = MainWindow(RealDatasetProvider())

    def reveal() -> None:
        window.show()
        window.raise_()
        window.activateWindow()
        # Closed after the window is up, so the last window never briefly becomes
        # zero, which would quit the app under setQuitOnLastWindowClosed.
        splash.close()

    QTimer.singleShot(SPLASH_MS, reveal)
    return app.exec()
