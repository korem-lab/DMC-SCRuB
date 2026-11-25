"""Child process entry point: `python -m dmcscrub_app.backend.process_main <request.json>`.

Contract with the parent:

- stdout carries the vendor's own printing verbatim for the run log
- stderr carries one JSON object per line, and nothing else
- exit code 0 means the manifest was written; anything else means it was not

Both streams are line-buffered because the parent reads them live; a full 8 KiB
buffer would make the progress bar arrive in bursts.
"""

from __future__ import annotations

import errno
import sys
import traceback
from datetime import datetime
from pathlib import Path

from dmcscrub_app.backend import manifest
from dmcscrub_app.backend.contracts import BackendRunRequest, EventSink
from dmcscrub_app.backend.runner import run_backend


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} <request.json>", file=sys.stderr)
        return 2

    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    events = EventSink(sys.stderr)
    try:
        request = BackendRunRequest.from_json(Path(argv[1]).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - nothing is known about the request yet
        events.failed(f"Could not read the run request: {exc}")
        traceback.print_exc()
        return 1

    created_at = datetime.now().isoformat(timespec="seconds")
    try:
        result = run_backend(request, events)
    except Exception as exc:  # noqa: BLE001 - any failure must reach the UI as text
        # The traceback goes to stdout so it lands in backend_stdout.log next to the
        # vendor's own output; stderr stays parseable.
        traceback.print_exc(file=sys.stdout)
        message = _user_message(exc)
        manifest.write_terminal_manifest(
            request.run_dir,
            status=manifest.STATUS_FAILED,
            dataset_name=request.dataset_name,
            count_path=str(request.count_path),
            metadata_path=str(request.metadata_path),
            created_at=created_at,
            algorithm=request.algorithm,
            error=message,
        )
        events.failed(message)
        return 1

    events.finished(result.manifest_path)
    return 0


def _user_message(exc: Exception) -> str:
    """Our own errors are already written for the user; anything else needs a type."""
    from dmcscrub_app.core.validation import InputValidationError

    if isinstance(exc, OSError) and exc.errno in (errno.ENOSPC, errno.EDQUOT):
        return (
            "Your computer does not have enough disk space. "
            "Please free up space and try again."
        )
    return str(exc) if isinstance(exc, InputValidationError) else f"{type(exc).__name__}: {exc}"


if __name__ == "__main__":
    sys.exit(main(sys.argv))
