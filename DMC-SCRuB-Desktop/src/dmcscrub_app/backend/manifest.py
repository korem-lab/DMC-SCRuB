"""Reading and writing `run_manifest.json`.

The child writes successful manifests, the parent records failed or cancelled
runs, and the history list reads them without importing the scientific backend.

The manifest is the run directory's self-description and the only data source for
the history list, so it holds scalars, ID lists and relative filenames -- never a
matrix.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dmcscrub_app.backend import paths

MANIFEST_SCHEMA_VERSION = 1

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


def write_manifest(run_dir: Path, payload: dict[str, Any]) -> Path:
    path = run_dir / paths.RUN_MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    return path


def read_manifest(run_dir: Path) -> dict[str, Any] | None:
    """None for directories with no readable manifest, i.e. leftovers of a kill."""
    path = run_dir / paths.RUN_MANIFEST
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_terminal_manifest(
    run_dir: Path,
    *,
    status: str,
    dataset_name: str,
    count_path: str,
    metadata_path: str,
    created_at: str,
    algorithm: str | None = None,
    error: str | None = None,
    notices: list[str] | None = None,
    warnings: list[str] | None = None,
    overwrite: bool = False,
) -> Path | None:
    """Write the manifest of a run that produced no results.

    Both processes call this, which is why it refuses by default to overwrite: the
    child writes one when it catches an exception, and the parent writes one only
    when the child died without getting the chance (an OOM kill, or a cancel).
    Returns None when a manifest was already there.
    """
    if not overwrite and (run_dir / paths.RUN_MANIFEST).exists():
        return None

    payload = base_payload(
        status=status,
        run_id=run_dir.name,
        created_at=created_at,
        dataset_name=dataset_name,
        count_path=count_path,
        metadata_path=metadata_path,
        algorithm=algorithm,
    )
    payload["finished_at"] = _now()
    payload["error"] = error
    payload["notices"] = list(notices or [])
    payload["warnings"] = list(warnings or [])
    return write_manifest(run_dir, payload)


def _now() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def base_payload(
    *,
    status: str,
    run_id: str,
    created_at: str,
    dataset_name: str,
    count_path: str,
    metadata_path: str,
    algorithm: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": status,
        "run_id": run_id,
        "created_at": created_at,
        "finished_at": None,
        "duration_seconds": None,
        "dataset_name": dataset_name,
        "count_path": count_path,
        "metadata_path": metadata_path,
        "algorithm": algorithm,
        "app_version": None,
        "column_mapping": {},
        "parameters": {},
        "counts": {},
        "notices": [],
        "warnings": [],
        "shapes": {},
        "outputs": {},
        "error": None,
    }
