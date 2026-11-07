"""DMC-SCRuB runner."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from dmcscrub_app.backend.concentration_outputs import write_concentration_outputs
from dmcscrub_app.backend.contracts import (
    STAGE_BUILDING_INPUTS,
    STAGE_FITTING,
    STAGE_SAVING,
    BackendRunRequest,
    BackendRunResult,
    EventSink,
)
from dmcscrub_app.backend.dmcscrub_checker import check_dmcscrub_inputs
from dmcscrub_app.backend.vendor.C_scrub_methods.DMC_SCRuB.c_scrub.base_c_SCRuB_fns import (
    fit_transform,
)
from dmcscrub_app.core.validation import InputValidationError


def run_dmcscrub(
    request: BackendRunRequest,
    events: EventSink,
    *,
    created_at: datetime,
) -> BackendRunResult:
    events.stage(STAGE_BUILDING_INPUTS)
    checked = check_dmcscrub_inputs(
        request.count_path,
        request.metadata_path,
        sample_column=request.column_mapping.sample_name,
        concentration_column=request.column_mapping.concentration,
        batch_column=request.column_mapping.batch,
        repair=request.repair_invalid,
    )
    _require_runnable(checked, request.repair_invalid)
    for notice in checked.notices:
        events.notice(notice)
    for warning in checked.repairable_issues:
        events.warning(warning)

    events.stage(STAGE_FITTING)
    assert checked.batches is not None
    batch_codes, batch_labels = pd.factorize(checked.batches, sort=False)
    batch_mapping = {
        str(label): int(code)
        for code, label in enumerate(batch_labels)
    }
    checked.notices.append(
        "Batch encoding: "
        + ", ".join(f"{label}={code}" for label, code in batch_mapping.items())
    )
    events.notice(checked.notices[-1])
    raw_result = fit_transform(
        checked.counts.to_numpy(dtype=float),
        checked.concentrations.to_numpy(dtype=float),
        batch_codes.astype(np.int64),
    )
    result = _result_frame(raw_result, checked.counts)

    events.stage(STAGE_SAVING)
    manifest_path = write_concentration_outputs(
        request,
        checked,
        result,
        created_at=created_at,
        batch_mapping=batch_mapping,
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
        raise InputValidationError("DMC-SCRuB returned a non-numeric result.") from exc
    if values.shape != template.shape:
        raise InputValidationError(
            f"DMC-SCRuB returned shape {values.shape}, expected {template.shape}."
        )
    if not np.isfinite(values).all():
        raise InputValidationError("DMC-SCRuB returned NaN or infinite values.")
    if (values < 0).any():
        raise InputValidationError("DMC-SCRuB returned negative values.")
    return pd.DataFrame(values, index=template.index, columns=template.columns)
