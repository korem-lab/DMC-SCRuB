"""CSV and manifest output shared by C-SCRuB and DMC-SCRuB."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from dmcscrub_app.backend import manifest, paths
from dmcscrub_app.backend.concentration_check import ConcentrationCheckResult
from dmcscrub_app.backend.contracts import BackendRunRequest

FLOAT_FORMAT = "%.6g"


def _app_version() -> str | None:
    try:
        from importlib.metadata import version

        return version("dmcscrub-app")
    except Exception:  # noqa: BLE001 - version is cosmetic metadata
        return None


def write_concentration_outputs(
    request: BackendRunRequest,
    checked: ConcentrationCheckResult,
    result: pd.DataFrame,
    *,
    created_at: datetime,
    batch_mapping: dict[str, int] | None = None,
    prediction_probabilities: pd.Series | None = None,
    parameters: dict[str, Any] | None = None,
) -> Path:
    run_dir = request.run_dir
    (run_dir / paths.RUN_DETAILS_DIR).mkdir(parents=True, exist_ok=True)
    id_column = request.column_mapping.sample_name

    relative = result.copy()
    relative.index.name = id_column
    relative.to_csv(run_dir / paths.RELATIVE_ABUNDANCE, float_format=FLOAT_FORMAT)

    outputs = {
        "decontaminated_relative_abundance": paths.RELATIVE_ABUNDANCE,
    }
    if prediction_probabilities is not None:
        predictions = prediction_probabilities.copy()
        predictions.index.name = id_column
        predictions.to_csv(
            run_dir / paths.PREDICTION_PROBABILITIES,
            float_format=FLOAT_FORMAT,
        )
        outputs["prediction_probabilities"] = paths.PREDICTION_PROBABILITIES

    finished_at = datetime.now()
    payload = manifest.base_payload(
        status=manifest.STATUS_SUCCESS,
        run_id=run_dir.name,
        created_at=created_at.isoformat(timespec="seconds"),
        dataset_name=request.dataset_name,
        count_path=str(request.count_path),
        metadata_path=str(request.metadata_path),
        algorithm=request.algorithm,
    )
    payload.update(
        {
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "duration_seconds": round((finished_at - created_at).total_seconds(), 1),
            "app_version": _app_version(),
            "column_mapping": asdict(request.column_mapping),
            "parameters": dict(parameters or {"method": "fit_transform"}),
            "counts": {
                "samples": result.shape[0],
                "taxa": result.shape[1],
                "batches": len(batch_mapping or {}) or 1,
            },
            "notices": list(checked.notices),
            "warnings": list(checked.repairable_issues),
            "repaired_cells": list(checked.repaired_cells),
            "batch_mapping": dict(batch_mapping or {}),
            "shapes": {
                "counts": list(checked.counts.shape),
                "metadata": list(checked.metadata_matrix.shape),
                "result": list(result.shape),
            },
            "outputs": outputs,
        }
    )
    return manifest.write_manifest(run_dir, payload)
