"""Owns the backend child process and turns its two output streams into signals.

The process boundary is what keeps a crash inside torch from taking the window
down with it, so this class is the only place that knows a child process exists.

Two streams, two jobs. stderr is our own JSON Lines protocol and becomes signals;
stdout is preserved verbatim in the run log for diagnostics.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from dmcscrub_app.backend import manifest, paths
from dmcscrub_app.backend.contracts import (
    EVENT_FAILED,
    EVENT_FINISHED,
    EVENT_NOTICE,
    EVENT_STAGE,
    EVENT_WARNING,
    BackendRunRequest,
    BackendRunResult,
)

TERMINATE_GRACE_MS = 2000
STDERR_TAIL_LINES = 5


class RunController(QObject):
    """One run at a time. `start` raises if the previous one is still alive."""

    stage_changed = Signal(str)
    notice = Signal(str)
    warning = Signal(str)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    running_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._request: BackendRunRequest | None = None
        self._created_at = ""
        self._stderr_buffer = ""
        self._stdout_buffer = ""
        self._stdout_log = None
        self._events_log = None
        self._stderr_tail: list[str] = []
        self._failure_message: str | None = None
        self._manifest_path: Path | None = None
        self._cancelling = False
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.setInterval(TERMINATE_GRACE_MS)
        self._kill_timer.timeout.connect(self._force_kill)

    @property
    def is_running(self) -> bool:
        return self._process is not None

    @property
    def run_dir(self) -> Path | None:
        return self._request.run_dir if self._request else None

    def start(self, request: BackendRunRequest) -> None:
        if self._process is not None:
            raise RuntimeError("A run is already in progress.")

        self._request = request
        self._created_at = datetime.now().isoformat(timespec="seconds")
        self._stderr_buffer = ""
        self._stdout_buffer = ""
        self._stderr_tail = []
        self._failure_message = None
        self._manifest_path = None
        self._cancelling = False

        # The request is written into the run directory rather than a temporary
        # file, so it is also a reproducible artefact of the run.
        (request.run_dir / paths.RUN_DETAILS_DIR).mkdir(parents=True, exist_ok=True)
        request_path = request.run_dir / paths.RUN_REQUEST
        request_path.write_text(request.to_json(), encoding="utf-8")
        self._stdout_log = open(request.run_dir / paths.BACKEND_STDOUT, "a", encoding="utf-8")
        self._events_log = open(request.run_dir / paths.BACKEND_EVENTS, "a", encoding="utf-8")

        process = QProcess(self)
        process.setProcessChannelMode(QProcess.SeparateChannels)
        environment = QProcessEnvironment.systemEnvironment()
        pythonpath = paths.child_pythonpath()
        if pythonpath:
            environment.insert("PYTHONPATH", pythonpath)
        else:
            # An installed build carries its own modules; see child_pythonpath.
            environment.remove("PYTHONPATH")
        # We decode both pipes as UTF-8 below, so the child has to encode as UTF-8.
        # On Windows it would otherwise use the console code page, and a traceback
        # naming a path with non-ASCII characters (C:\Users\<name>\...) would kill
        # the child with a UnicodeEncodeError while it was trying to explain itself.
        environment.insert("PYTHONIOENCODING", "utf-8")
        process.setProcessEnvironment(environment)
        process.readyReadStandardError.connect(self._read_stderr)
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        self._process = process

        command = paths.child_command(request_path)
        self.running_changed.emit(True)
        process.start(command[0], command[1:])

    def cancel(self) -> None:
        """Ask politely, then insist. The run directory is kept either way."""
        if self._process is None or self._cancelling:
            return
        self._cancelling = True
        request = self._request
        if request is not None:
            manifest.write_terminal_manifest(
                request.run_dir,
                status=manifest.STATUS_CANCELLED,
                dataset_name=request.dataset_name,
                count_path=str(request.count_path),
                metadata_path=str(request.metadata_path),
                created_at=self._created_at,
                algorithm=request.algorithm,
            )
        self._process.terminate()
        self._kill_timer.start()

    def _force_kill(self) -> None:
        if self._process is not None:
            self._process.kill()

    # --- stream handling ----------------------------------------------------

    def _read_stderr(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardError()).decode("utf-8", "replace")
        self._stderr_buffer += chunk
        lines = self._stderr_buffer.split("\n")
        self._stderr_buffer = lines.pop()
        for raw in lines:
            # On Windows the child's "\n" reaches us as "\r\n".
            line = raw.rstrip("\r")
            self._write_log(self._events_log, line + "\n")
            if line.strip():
                self._handle_event_line(line)

    def _read_stdout(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        self._stdout_buffer += chunk
        lines = self._stdout_buffer.split("\n")
        self._stdout_buffer = lines.pop()
        for raw in lines:
            line = raw.rstrip("\r")
            self._write_log(self._stdout_log, line + "\n")

    def _handle_event_line(self, line: str) -> None:
        try:
            event = json.loads(line)
        except ValueError:
            # A malformed line loses one event; killing the run over it would lose
            # the whole fit. It is kept, though: when the child dies before it can
            # emit anything -- a failed import, say -- Python's own traceback comes
            # out here and is the only explanation available.
            self._stderr_tail.append(line.strip())
            del self._stderr_tail[:-STDERR_TAIL_LINES]
            return
        event_type = event.get("type")

        if event_type == EVENT_STAGE:
            self.stage_changed.emit(event.get("value", ""))
        elif event_type == EVENT_NOTICE:
            self.notice.emit(event.get("text", ""))
        elif event_type == EVENT_WARNING:
            self.warning.emit(event.get("text", ""))
        elif event_type == EVENT_FINISHED:
            self._manifest_path = Path(event["manifest"])
        elif event_type == EVENT_FAILED:
            self._failure_message = event.get("message") or "The run failed."

    @staticmethod
    def _write_log(handle, text: str) -> None:
        if handle is None:
            return
        try:
            handle.write(text)
            handle.flush()
        except OSError:
            pass

    # --- termination --------------------------------------------------------

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.FailedToStart:
            message = (
                "The backend process could not be started. Check that the "
                "application's Python environment is intact."
            )
            request = self._request
            self._request = None
            self._kill_timer.stop()
            self._close_logs()
            process = self._process
            self._process = None
            if process is not None:
                process.deleteLater()
            self.running_changed.emit(False)
            if request is not None:
                manifest.write_terminal_manifest(
                    request.run_dir,
                    status=manifest.STATUS_FAILED,
                    dataset_name=request.dataset_name,
                    count_path=str(request.count_path),
                    metadata_path=str(request.metadata_path),
                    created_at=self._created_at,
                    algorithm=request.algorithm,
                    error=message,
                )
            self.failed.emit(message)

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        request = self._request
        self._request = None
        self._kill_timer.stop()
        self._drain_buffers()
        self._close_logs()

        process = self._process
        self._process = None
        if process is not None:
            process.deleteLater()
        self.running_changed.emit(False)

        if request is None:
            return

        if self._cancelling:
            manifest.write_terminal_manifest(
                request.run_dir,
                status=manifest.STATUS_CANCELLED,
                dataset_name=request.dataset_name,
                count_path=str(request.count_path),
                metadata_path=str(request.metadata_path),
                created_at=self._created_at,
                algorithm=request.algorithm,
            )
            self.cancelled.emit()
            return

        crashed = exit_status == QProcess.CrashExit
        if exit_code == 0 and self._manifest_path is not None and not crashed:
            self.finished.emit(
                BackendRunResult(run_dir=request.run_dir, manifest_path=self._manifest_path)
            )
            return

        message = self._failure_message or self._synthesised_failure(exit_code, crashed)
        # A child that was killed never got to write its own manifest, so the run
        # would otherwise be invisible in history. write_terminal_manifest does
        # nothing when the child managed to write one.
        manifest.write_terminal_manifest(
            request.run_dir,
            status=manifest.STATUS_FAILED,
            dataset_name=request.dataset_name,
            count_path=str(request.count_path),
            metadata_path=str(request.metadata_path),
            created_at=self._created_at,
            algorithm=request.algorithm,
            error=message,
        )
        self.failed.emit(message)

    def _synthesised_failure(self, exit_code: int, crashed: bool) -> str:
        """The child died without saying why: an OOM kill, or a broken interpreter."""
        reason = (
            "may have run out of memory"
            if crashed
            else f"exited with code {exit_code}"
        )
        message = f"The backend process stopped unexpectedly and {reason}."
        if self._stderr_tail:
            message += f" Last output: {self._stderr_tail[-1]}"
        return f"{message} See {paths.BACKEND_STDOUT} in the run folder."

    def _drain_buffers(self) -> None:
        """Whatever arrived without a trailing newline still has to be logged."""
        if self._process is not None:
            self._read_stderr()
            self._read_stdout()
        if self._stderr_buffer.strip():
            self._write_log(self._events_log, self._stderr_buffer + "\n")
            self._handle_event_line(self._stderr_buffer)
        if self._stdout_buffer.strip():
            self._write_log(self._stdout_log, self._stdout_buffer + "\n")
        self._stderr_buffer = ""
        self._stdout_buffer = ""

    def _close_logs(self) -> None:
        """Explicit flush and close.

        Left open, the run directory cannot be deleted on Windows and a zip built
        from it can contain a truncated log.
        """
        for attribute in ("_stdout_log", "_events_log"):
            handle = getattr(self, attribute)
            if handle is None:
                continue
            try:
                handle.flush()
                handle.close()
            except OSError:
                pass
            setattr(self, attribute, None)
