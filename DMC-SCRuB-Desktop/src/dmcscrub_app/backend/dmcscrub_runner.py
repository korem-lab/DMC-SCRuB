"""DMC-SCRuB runner."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import torch
from dmc_scrub import DMC_SCRuB_Classifier

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
from dmcscrub_app.core.validation import InputValidationError

MODEL_SEED = 123


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
        label_column=request.column_mapping.label,
        positive_value=request.column_mapping.positive_value,
        repair=request.repair_invalid,
    )
    _require_runnable(checked, request.repair_invalid)
    for notice in checked.notices:
        events.notice(notice)
    for warning in checked.repairable_issues:
        events.warning(warning)

    assert checked.batches is not None
    assert checked.labels is not None
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

    sample_matrix = checked.counts.to_numpy(dtype=float)
    concentration = checked.concentrations.to_numpy(dtype=float)
    x_with_batch = np.column_stack([batch_codes.astype(float), sample_matrix])

    test_batch_code = len(batch_labels) - 1
    test_mask = batch_codes == test_batch_code
    train_mask = ~test_mask
    labels = checked.labels.to_numpy(dtype=float)

    test_batch = str(batch_labels[test_batch_code])
    notice = (
        f"DMC-SCRuB label {request.column_mapping.label!r}: "
        f"{request.column_mapping.positive_value!r}=1, all other values=0; "
        f"held-out test batch={test_batch!r}."
    )
    checked.notices.append(notice)
    events.notice(notice)

    events.stage(STAGE_FITTING)
    np.random.seed(MODEL_SEED)
    torch.manual_seed(MODEL_SEED)
    model = DMC_SCRuB_Classifier(
        x_val=x_with_batch[test_mask],
        mu_val=concentration[test_mask],
        random_state=MODEL_SEED,
    )
    model.fit(
        x_with_batch[train_mask],
        labels[train_mask],
        concentration[train_mask],
    )
    transformed = model.transform()
    raw_result = np.empty_like(sample_matrix, dtype=float)
    raw_result[train_mask] = _to_numpy(transformed["Train_X"])
    raw_result[test_mask] = _to_numpy(transformed["Test_X"])
    result = _result_frame(raw_result, checked.counts)

    predictions = pd.Series(
        np.asarray(model.predict_proba(), dtype=float),
        index=checked.counts.index[test_mask],
        name="prediction_probability",
    )

    events.stage(STAGE_SAVING)
    manifest_path = write_concentration_outputs(
        request,
        checked,
        result,
        created_at=created_at,
        batch_mapping=batch_mapping,
        prediction_probabilities=predictions,
        parameters={
            "method": "DMC_SCRuB_Classifier",
            "label_column": request.column_mapping.label,
            "positive_value": request.column_mapping.positive_value,
            "model_seed": MODEL_SEED,
            "test_batch": test_batch,
            "test_batch_code": test_batch_code,
        },
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

def _to_numpy(value) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    return np.asarray(value.numpy() if hasattr(value, "numpy") else value, dtype=float)


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
