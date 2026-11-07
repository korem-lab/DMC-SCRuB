"""Application shell: toolbar + tabs for datasets, history and run details.

Orchestration only. It owns a `DatasetProvider` (the backend seam), opens the
startup dialog to create datasets, and enforces the one rule that spans tabs: at
most one run in flight at a time.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QToolButton,
    QWidget,
)

from dmcscrub_app.backend import history
from dmcscrub_app.ui.data_provider import DatasetProvider
from dmcscrub_app.ui.dialogs.cscrub_startup_dialog import CScrubStartupDialog
from dmcscrub_app.ui.metadata_error_messages import metadata_error_message
from dmcscrub_app.ui.models import (
    ALGORITHM_C_SCRUB,
    ALGORITHM_DMC_SCRUB,
    DatasetConfig,
)
from dmcscrub_app.ui.tutorial_content import (
    TUTORIAL_STATUS_TEXT,
    TUTORIAL_TAB_TEXT,
    TUTORIAL_TOOLBAR_TEXT,
)
from dmcscrub_app.ui.views.dataset_view import DatasetView
from dmcscrub_app.ui.views.history_view import HistoryView
from dmcscrub_app.ui.views.run_detail_view import RunDetailView
from dmcscrub_app.ui.views.tutorial_view import TutorialView
from dmcscrub_app.ui.widgets.dataset_tab_widget import DatasetTabWidget


class MainWindow(QMainWindow):
    def __init__(self, provider: DatasetProvider) -> None:
        super().__init__()
        self._provider = provider
        self.setWindowTitle("DMC-SCRuB DESKTOP")
        self.resize(1180, 760)

        # Debris from a killed process: a run directory with no manifest. Cleaned at
        # startup rather than at shutdown, because being killed is precisely what
        # skips the shutdown path.
        history.prune_incomplete()

        self._build_toolbar()

        self._history_view: HistoryView | None = None
        self._tutorial_view: TutorialView | None = None

        self.tabs = DatasetTabWidget()
        self.tabs.add_requested.connect(self._show_upload_menu_at_add_button)
        self.tabs.dataset_renamed.connect(self._rename_dataset)
        self.tabs.tabCloseRequested.connect(self._close_tab_at)
        self.tabs.currentChanged.connect(lambda _index: self._update_status())

        self.setStatusBar(QStatusBar())

        self._empty_state = self._build_empty_state()

        self.stack = QStackedWidget()
        self.stack.addWidget(self._empty_state)
        self.stack.addWidget(self.tabs)
        self.setCentralWidget(self.stack)

        self._update_stack()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setObjectName("mainToolbar")
        self.addToolBar(toolbar)

        home_action = QAction("\U0001F3E0  Home", self)
        home_action.triggered.connect(self._go_home)
        self._upload_menu = QMenu(self)
        self._upload_menu.setObjectName("uploadMenu")
        for algorithm in (ALGORITHM_C_SCRUB, ALGORITHM_DMC_SCRUB):
            self._upload_menu.addAction(
                algorithm,
                lambda checked=False, selected=algorithm: self._open_algorithm_dialog(
                    selected
                ),
            )
        upload_button = QToolButton()
        upload_button.setObjectName("uploadButton")
        upload_button.setText("\u2B06  Upload")
        upload_button.setMenu(self._upload_menu)
        upload_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        upload_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        upload_button.setAutoRaise(True)
        reload_action = QAction("\u21BB  Reload", self)
        reload_action.triggered.connect(self._reload_current)
        history_action = QAction("\U0001F553  History", self)
        history_action.triggered.connect(self._show_history)
        tutorial_action = QAction(TUTORIAL_TOOLBAR_TEXT, self)
        tutorial_action.triggered.connect(self._show_tutorial)

        toolbar.addAction(home_action)
        toolbar.addSeparator()
        toolbar.addWidget(upload_button)
        toolbar.addAction(reload_action)
        toolbar.addAction(history_action)
        toolbar.addSeparator()
        toolbar.addAction(tutorial_action)

    def _build_empty_state(self) -> QWidget:
        placeholder = QLabel("No dataset loaded.\nUse Upload to open a dataset.")
        placeholder.setObjectName("emptyState")
        placeholder.setAlignment(Qt.AlignCenter)
        return placeholder

    def _show_upload_menu_at_add_button(self) -> None:
        self._upload_menu.popup(self.tabs.add_button_popup_pos())

    def _open_algorithm_dialog(
        self,
        algorithm: str,
    ) -> None:
        dialog = CScrubStartupDialog(
            self._provider,
            algorithm,
            parent=self,
        )
        self._open_upload_dialog(dialog)

    def _open_upload_dialog(
        self,
        dialog: CScrubStartupDialog,
    ) -> None:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            config = dialog.dataset_config()
            self._add_dataset(config)
        except Exception as exc:
            message = metadata_error_message(exc)
            QMessageBox.critical(self, "Could Not Open Dataset", message)

    def _add_dataset(self, config: DatasetConfig) -> None:
        dataset = self._provider.build_dataset(config)
        view = DatasetView(dataset)
        self._configure_dataset_view(view)
        index = self.tabs.addTab(view, config.name)
        self.tabs.setCurrentIndex(index)
        self._update_stack()

    def _configure_dataset_view(self, view: DatasetView) -> None:
        """Attach window-level run coordination to a dataset view."""
        view.set_run_guard(lambda v=view: self._guard_run(v))
        view.controller.running_changed.connect(self._on_running_changed)
        view.controller.finished.connect(lambda _result: self._refresh_history())
        view.controller.failed.connect(lambda _message: self._refresh_history())
        view.controller.cancelled.connect(self._refresh_history)

    def _guard_run(self, view: DatasetView) -> bool:
        """One run at a time, across every tab.

        Return False before DatasetView starts if a different tab is active.
        """
        other = self._running_view()
        if other is not None and other is not view:
            QMessageBox.information(
                self,
                "Another Run Is Active",
                f"'{other.config.name}' is still running. Wait for it to finish or "
                "cancel it before starting another run.",
            )
            return False
        return True

    def _running_view(self) -> DatasetView | None:
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, DatasetView) and widget.is_running:
                return widget
        return None

    def _active_run_dir(self) -> Path | None:
        view = self._running_view()
        return view.active_run_dir if view is not None else None

    def _on_running_changed(self, _running: bool) -> None:
        if self._history_view is not None:
            self._history_view.set_active_run_dir(self._active_run_dir())
        self._update_status()

    def _refresh_history(self) -> None:
        if self._history_view is not None:
            self._history_view.set_active_run_dir(self._active_run_dir())
            self._history_view.refresh()

    def _reload_current(self) -> None:
        index = self.tabs.currentIndex()
        current = self.tabs.currentWidget()
        if index < 0 or not isinstance(current, DatasetView):
            return
        if not self._confirm_discard_run(current, "reload this dataset"):
            return
        config = current.config
        try:
            dataset = self._provider.build_dataset(config)
            new_view = DatasetView(dataset)
            self._configure_dataset_view(new_view)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Could Not Reload Dataset",
                f"Reload failed:\n{exc}",
            )
            return
        self.tabs.removeTab(index)
        self.tabs.insertTab(index, new_view, config.name)
        self.tabs.setCurrentIndex(index)
        current.deleteLater()

    def _close_tab_at(self, index: int) -> None:
        if index < 0:
            return
        widget = self.tabs.widget(index)
        if isinstance(widget, DatasetView) and not self._confirm_discard_run(
            widget, "close this tab"
        ):
            return
        if widget is self._history_view:
            self._history_view = None
        if widget is self._tutorial_view:
            self._tutorial_view = None
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()
        self._update_stack()

    def _confirm_discard_run(self, view: DatasetView, action: str) -> bool:
        """Destroying a view whose child process is alive would orphan it."""
        if not view.is_running:
            return True
        confirm = QMessageBox.question(
            self,
            "Run In Progress",
            f"'{view.config.name}' is still running. Cancel the run and {action}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return False
        view.cancel_run()
        return True

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        view = self._running_view()
        if view is not None and not self._confirm_discard_run(view, "quit"):
            event.ignore()
            return
        super().closeEvent(event)

    def _rename_dataset(self, index: int, name: str) -> None:
        view = self.tabs.widget(index)
        if isinstance(view, DatasetView):
            view.rename(name)
            self._update_status()

    def _go_home(self) -> None:
        # Index 0 may be a history or detail tab if history was opened before any
        # dataset. That is acceptable; special-casing it would be more surprising.
        if self.tabs.count() > 0:
            self.tabs.setCurrentIndex(0)

    def _show_history(self) -> None:
        """Open the history list tab, or switch to it if it is already open."""
        if self._history_view is not None:
            self._select_tab(self._history_view)
            self._refresh_history()
            return
        view = HistoryView()
        view.set_active_run_dir(self._active_run_dir())
        view.run_opened.connect(self._open_run_detail)
        view.runs_deleted.connect(self._close_detail_tabs_for)
        self._history_view = view
        index = self.tabs.addTab(view, "History")
        self.tabs.setCurrentIndex(index)
        self._update_stack()

    def _show_tutorial(self) -> None:
        """Open the tutorial tab, or switch to it if it is already open."""
        if self._tutorial_view is not None:
            self._select_tab(self._tutorial_view)
            return
        self._tutorial_view = TutorialView()
        index = self.tabs.addTab(self._tutorial_view, TUTORIAL_TAB_TEXT)
        self.tabs.setCurrentIndex(index)
        self._update_stack()

    def _open_run_detail(self, summary) -> None:
        # Dedupe by run id: clicking a row twice should switch to the tab that is
        # already open, not produce two identical pages.
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, RunDetailView) and widget.run_id == summary.run_id:
                self.tabs.setCurrentIndex(index)
                return
        view = RunDetailView(summary)
        index = self.tabs.addTab(view, view.tab_title())
        self.tabs.setCurrentIndex(index)
        self._update_stack()

    def _close_detail_tabs_for(self, run_dirs) -> None:
        """A detail tab pointing at a deleted directory fails on any download."""
        deleted = {Path(path).resolve() for path in run_dirs}
        for index in reversed(range(self.tabs.count())):
            widget = self.tabs.widget(index)
            if isinstance(widget, RunDetailView) and widget.run_dir.resolve() in deleted:
                self.tabs.removeTab(index)
                widget.deleteLater()
        self._update_stack()

    def _select_tab(self, widget: QWidget) -> None:
        index = self.tabs.indexOf(widget)
        if index >= 0:
            self.tabs.setCurrentIndex(index)

    def _update_stack(self) -> None:
        self.stack.setCurrentWidget(self.tabs if self.tabs.count() > 0 else self._empty_state)
        self._update_status()

    def _update_status(self) -> None:
        current = self.tabs.currentWidget()
        if isinstance(current, DatasetView):
            self.statusBar().showMessage(current.status_text())
        elif isinstance(current, TutorialView):
            self.statusBar().showMessage(TUTORIAL_STATUS_TEXT)
        else:
            self.statusBar().showMessage("Ready \u00b7 use Upload to open a dataset")
