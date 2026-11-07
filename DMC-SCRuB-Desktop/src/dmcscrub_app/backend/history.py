"""History as a scan of `runs/`, not as a database.

The directory is the only source of truth, which makes the feature self-healing:
"appears in history" simply means "has a manifest", so there is no bookkeeping to
get out of sync when a run crashes or a user deletes a folder by hand.

Standard library plus `paths`/`manifest` only. The UI imports this, so it must not
pull pandas or torch in. A `RunSummary` holds scalars and paths -- never a table --
which is what keeps a hundred runs from filling memory.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dmcscrub_app.backend import manifest, paths
from dmcscrub_app.backend.contracts import ALGORITHM_C_SCRUB, ALGORITHMS


@dataclass(frozen=True)
class RunSummary:
    run_dir: Path
    run_id: str
    status: str
    algorithm: str
    dataset_name: str
    created_at: str
    finished_at: str | None
    duration_seconds: float | None
    samples: int | None
    taxa: int | None
    error: str | None
    notice_count: int
    warning_count: int
    size_bytes: int

    @property
    def has_results(self) -> bool:
        return self.status == manifest.STATUS_SUCCESS

    @property
    def can_open_details(self) -> bool:
        """Cancelled runs have nothing to show, so their row stays inert.

        A detail page that opens onto blank panels is worse than a row that does
        not open at all.
        """
        return self.status in (manifest.STATUS_SUCCESS, manifest.STATUS_FAILED)


def list_runs(root: Path | None = None) -> list[RunSummary]:
    """Return runs newest first by their recorded creation time."""
    base = root or paths.runs_root()
    if not base.is_dir():
        return []
    summaries: list[RunSummary] = []
    for run_dir in base.iterdir():
        summary = load_summary(run_dir)
        if summary is not None:
            summaries.append(summary)
    return sorted(summaries, key=lambda item: item.created_at, reverse=True)


def load_summary(run_dir: Path) -> RunSummary | None:
    """None for anything that is not a finished run directory."""
    if not run_dir.is_dir():
        return None
    payload = manifest.read_manifest(run_dir)
    if payload is None:
        return None

    counts = payload.get("counts") or {}
    algorithm = payload.get("algorithm") or ALGORITHM_C_SCRUB
    if algorithm not in ALGORITHMS:
        return None
    return RunSummary(
        run_dir=run_dir,
        run_id=payload.get("run_id") or run_dir.name,
        status=payload.get("status") or manifest.STATUS_FAILED,
        algorithm=algorithm,
        dataset_name=payload.get("dataset_name") or run_dir.name,
        created_at=payload.get("created_at") or "",
        finished_at=payload.get("finished_at"),
        duration_seconds=payload.get("duration_seconds"),
        samples=counts.get("samples"),
        taxa=counts.get("taxa"),
        error=payload.get("error"),
        notice_count=len(payload.get("notices") or []),
        warning_count=len(payload.get("warnings") or []),
        size_bytes=directory_size(run_dir),
    )


def delete_runs(
    run_dirs: Sequence[Path], exclude: Path | None = None
) -> list[tuple[Path, str]]:
    """Delete each directory, returning the ones that could not be removed.

    Failures are collected rather than raised: in a multi-select delete, one locked
    file must not leave the other selected runs in place.

    `exclude` is the currently running run's directory and is skipped
    unconditionally. It normally has no manifest yet and so is absent from the
    list, but this is the second line of defence and the reason `Clear` deletes
    listed entries instead of the whole root.
    """
    failures: list[tuple[Path, str]] = []
    excluded = exclude.resolve() if exclude else None
    for run_dir in run_dirs:
        if excluded is not None and run_dir.resolve() == excluded:
            continue
        try:
            shutil.rmtree(run_dir)
        except OSError as exc:
            failures.append((run_dir, exc.strerror or str(exc)))
    return failures


def is_debris(run_dir: Path) -> bool:
    """Did we create this directory and fail to finish it?

    Debris is identified by what it contains, not by what it lacks. "No manifest"
    alone would also match any directory that is simply not ours -- output from an
    older version, or a folder the user put there -- and deleting those without
    asking is not something a tool gets to do. The parent process writes both
    marker files before the fit can start, so real debris always has one.
    """
    if (run_dir / paths.RUN_MANIFEST).exists():
        return False
    return (
        (run_dir / paths.RUN_REQUEST).exists()
        or (run_dir / paths.VIEW_SNAPSHOT).exists()
    )


def prune_incomplete(root: Path | None = None, exclude: Path | None = None) -> int:
    """Remove leftovers of killed processes.

    Called once at application startup rather than at shutdown, because the
    shutdown path is exactly what gets skipped when the process is killed.
    """
    base = root or paths.runs_root()
    if not base.is_dir():
        return 0
    excluded = exclude.resolve() if exclude else None
    removed = 0
    for run_dir in base.iterdir():
        if not run_dir.is_dir() or not is_debris(run_dir):
            continue
        if excluded is not None and run_dir.resolve() == excluded:
            continue
        try:
            shutil.rmtree(run_dir)
            removed += 1
        except OSError:
            continue
    return removed


def directory_size(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def total_size_bytes(root: Path | None = None) -> int:
    base = root or paths.runs_root()
    return directory_size(base) if base.is_dir() else 0


def format_size(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    for unit in ("KB", "MB", "GB"):
        value /= 1024.0
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} GB"
