"""C-SCRuB input checker."""

from __future__ import annotations

from pathlib import Path

from dmcscrub_app.backend.concentration_check import (
    ConcentrationCheckResult,
    check_concentration_inputs,
)


def check_cscrub_inputs(
    count_path: Path,
    metadata_path: Path,
    *,
    sample_column: str,
    concentration_column: str,
    repair: bool = False,
) -> ConcentrationCheckResult:
    checked = check_concentration_inputs(
        count_path,
        metadata_path,
        sample_column=sample_column,
        concentration_column=concentration_column,
        batch_column=None,
        repair=repair,
    )
    if checked.hard_errors:
        return checked
    if checked.counts.shape[0] < 2:
        checked.hard_errors.append("C-SCRuB needs at least two samples.")
    elif checked.concentrations.nunique() < 2:
        checked.hard_errors.append(
            "C-SCRuB needs at least two distinct concentration values."
        )
    return checked
