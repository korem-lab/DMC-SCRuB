"""Run directory location, naming and output filenames.

Standard library only: the UI imports this to create run directories and to list
history, and must not pull pandas or torch in along the way.

`runs_root()` is the single place that decides where runs live.
"""

from __future__ import annotations

import os
import re
import secrets
import sys
from datetime import datetime
from pathlib import Path

CHILD_MODULE = "dmcscrub_app.backend.process_main"
APP_DIR_NAME = "DMC-SCRuB DESKTOP"

RUN_DETAILS_DIR = "run_details"
RUN_MANIFEST = f"{RUN_DETAILS_DIR}/run_manifest.json"
RUN_REQUEST = f"{RUN_DETAILS_DIR}/run_request.json"
VIEW_SNAPSHOT = f"{RUN_DETAILS_DIR}/view_snapshot.json"
BACKEND_STDOUT = f"{RUN_DETAILS_DIR}/backend_stdout.log"
BACKEND_EVENTS = f"{RUN_DETAILS_DIR}/backend_events.jsonl"

RELATIVE_ABUNDANCE = "decontaminated_relative_abundance.csv"

# Menu order for the download entries, label -> filename.
DOWNLOAD_ITEMS: tuple[tuple[str, str], ...] = (
    ("Decontaminated relative abundance", RELATIVE_ABUNDANCE),
)

_SLUG_ALLOWED = re.compile(r"[^A-Za-z0-9._-]+")
_SLUG_MAX_LENGTH = 40


def user_data_root() -> Path:
    """Where the application keeps everything it writes.

    Each platform's own convention, so an uninstaller and a backup tool both find
    it where they expect. Qt would answer this too, but the backend imports this
    module and must not pull PySide6 into the child process to do so.
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME


def runs_root() -> Path:
    """Directory holding one subdirectory per run."""
    return user_data_root() / "runs"


def child_command(request_path: Path) -> list[str]:
    """How to launch the backend process."""
    return [sys.executable, "-u", "-m", CHILD_MODULE, str(request_path)]


def package_root() -> Path:
    """The directory that contains the `dmcscrub_app` package."""
    return Path(__file__).resolve().parents[2]


def child_pythonpath() -> str:
    """PYTHONPATH for the child, so its imports do not depend on ours.

    `-m` resolves the module through the child's own import path. The parent may
    have found the package through a path entry that no environment variable
    mentions -- a source checkout added to `sys.path` -- in which case the child
    would fail to import before it could report anything.

    Existing entries are preserved after the installed package root.
    """
    entries = [str(package_root())]
    entries.extend(part for part in os.environ.get("PYTHONPATH", "").split(os.pathsep) if part)
    return os.pathsep.join(dict.fromkeys(entries))


def slugify_dataset_name(name: str) -> str:
    """Tab titles are user-editable, so they may contain anything."""
    slug = _SLUG_ALLOWED.sub("_", name.strip()).strip("_")
    return slug[:_SLUG_MAX_LENGTH] or "dataset"


def new_run_id(dataset_name: str, *, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    suffix = f"{secrets.randbelow(10000):04d}"
    return f"{slugify_dataset_name(dataset_name)}_{stamp}_{suffix}"


def create_run_dir(dataset_name: str, *, root: Path | None = None) -> Path:
    """Create and return a fresh run directory.

    Called by the UI when Run is clicked, so the parent process can write the view
    snapshot and both logs from the very first moment, and so deleting a cancelled
    run has a single owner.
    """
    base = root or runs_root()
    base.mkdir(parents=True, exist_ok=True)
    while True:
        run_dir = base / new_run_id(dataset_name)
        try:
            run_dir.mkdir()
        except FileExistsError:
            continue
        (run_dir / RUN_DETAILS_DIR).mkdir()
        return run_dir
