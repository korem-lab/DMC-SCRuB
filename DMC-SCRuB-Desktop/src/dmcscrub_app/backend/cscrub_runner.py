"""C-SCRuB runner."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
from dmc_scrub import C_SCRuB

from dmcscrub_app.backend.concentration_outputs import write_concentration_outputs
from dmcscrub_app.backend.contracts import (
    STAGE_BUILDING_INPUTS,
    STAGE_FITTING,
    STAGE_SAVING,
    BackendRunRequest,
    BackendRunResult,
    EventSink,
)
from dmcscrub_app.backend.cscrub_checker import check_cscrub_inputs
from dmcscrub_app.core.validation import InputValidationError


def run_cscrub(
    request: BackendRunRequest,
    events: EventSink,
    *,
    created_at: datetime,
) -> BackendRunResult:
    events.stage(STAGE_BUILDING_INPUTS)
    checked = check_cscrub_inputs(
        request.count_path,
        request.metadata_path,
        sample_column=request.column_mapping.sample_name,
        concentration_column=request.column_mapping.concentration,
        repair=request.repair_invalid,
    )
    _require_runnable(checked, request.repair_invalid)
    for notice in checked.notices:
        events.notice(notice)
    for warning in checked.repairable_issues:
        events.warning(warning)

    events.stage(STAGE_FITTING)
    sample_matrix = checked.counts.to_numpy(dtype=float)
    concentration = checked.concentrations.to_numpy(dtype=float)
    raw_result = C_SCRuB().fit_transform(sample_matrix, concentration)
    result = _result_frame(raw_result, checked.counts)

    events.stage(STAGE_SAVING)
    manifest_path = write_concentration_outputs(
        request,
        checked,
        result,
        created_at=created_at,
    )
    return BackendRunResult(run_dir=request.run_dir, manifest_path=manifest_path)


def _require_runnable(checked, repair_invalid: bool) -> None:
    if checked.hard_errors:
        raise InputValidationError("\n".join(checked.hard_errors))
    if checked.repairable_issues and not repair_invalid:
        raise InputValidationError(
            "Input contains repairable problems. Confirm Run Anyway to replace "
            "invalid numeric cells with 0."
        )


def _result_frame(raw_result, template: pd.DataFrame) -> pd.DataFrame:
    try:
        values = np.asarray(raw_result, dtype=float)
    except (TypeError, ValueError) as exc:
        raise InputValidationError("C-SCRuB returned a non-numeric result.") from exc
    if values.shape != template.shape:
        raise InputValidationError(
            f"C-SCRuB returned shape {values.shape}, expected {template.shape}."
        )
    if not np.isfinite(values).all():
        raise InputValidationError("C-SCRuB returned NaN or infinite values.")
    if (values < 0).any():
        raise InputValidationError("C-SCRuB returned negative values.")
    return pd.DataFrame(values, index=template.index, columns=template.columns)
