"""Shared input preparation for concentration-based algorithms."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from dmcscrub_app.core.io import read_count_table, read_metadata_table

_EMPTY_BATCH_VALUES = {"", "nan", "none", "na", "<na>"}


@dataclass
class ConcentrationCheckResult:
    counts: pd.DataFrame = field(default_factory=pd.DataFrame)
    metadata_matrix: np.ndarray = field(
        default_factory=lambda: np.empty((0, 0), dtype=float)
    )
    concentrations: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    batches: pd.Series | None = None
    hard_errors: list[str] = field(default_factory=list)
    repairable_issues: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    repaired_cells: list[dict[str, str]] = field(default_factory=list)

    @property
    def can_run(self) -> bool:
        return not self.hard_errors and self.metadata_matrix.size > 0


def check_concentration_inputs(
    count_path: Path,
    metadata_path: Path,
    *,
    sample_column: str,
    concentration_column: str,
    batch_column: str | None,
    repair: bool,
) -> ConcentrationCheckResult:
    result = ConcentrationCheckResult()
    selected = [sample_column, concentration_column]
    if batch_column:
        selected.append(batch_column)
    if any(not column for column in selected):
        result.hard_errors.append("Every required metadata column must be selected.")
        return result
    if len(set(selected)) != len(selected):
        result.hard_errors.append("Selected metadata columns must be different.")
        return result

    try:
        raw_counts = read_count_table(count_path)
    except Exception as exc:  # noqa: BLE001 - checker reports file errors uniformly
        result.hard_errors.append(f"Cannot read the count table: {exc}")
        return result
    try:
        raw_metadata = read_metadata_table(metadata_path)
    except Exception as exc:  # noqa: BLE001 - checker reports file errors uniformly
        result.hard_errors.append(f"Cannot read the metadata table: {exc}")
        return result

    if raw_counts.empty:
        result.hard_errors.append("Count table is empty.")
    if raw_counts.shape[1] == 0:
        result.hard_errors.append("Count table has no feature columns.")
    if raw_counts.index.has_duplicates:
        result.hard_errors.append("Count table sample IDs must be unique.")
    if raw_metadata.empty:
        result.hard_errors.append("Metadata table is empty.")

    missing_columns = set(selected) - set(raw_metadata.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        result.hard_errors.append(f"Metadata is missing selected columns: {missing}")
    if result.hard_errors:
        return result

    sample_values = raw_metadata[sample_column]
    empty_sample = sample_values.isna() | sample_values.astype(str).str.strip().eq("")
    if empty_sample.any():
        result.hard_errors.append("Metadata sample names must be non-empty.")
        return result
    sample_values = sample_values.astype(str)
    if sample_values.duplicated().any():
        duplicates = sample_values[sample_values.duplicated(keep=False)].unique()
        result.hard_errors.append(
            "Metadata sample names must be unique: "
            + ", ".join(str(value) for value in duplicates[:5])
        )
        return result

    metadata = raw_metadata.copy()
    metadata.index = sample_values
    missing_metadata = raw_counts.index.difference(metadata.index)
    if not missing_metadata.empty:
        examples = ", ".join(missing_metadata[:5].astype(str).tolist())
        result.hard_errors.append(
            f"Metadata is missing rows for count table IDs: {examples}"
        )
        return result
    extra_metadata = metadata.index.difference(raw_counts.index)
    if not extra_metadata.empty:
        result.notices.append(
            f"{len(extra_metadata)} metadata row(s) not present in the count table "
            "were ignored."
        )
    metadata = metadata.loc[raw_counts.index]

    result.counts = _numeric_table(
        raw_counts,
        table_name="Count table",
        repair=repair,
        result=result,
    )
    result.concentrations = _numeric_series(
        metadata[concentration_column],
        column_name=concentration_column,
        repair=repair,
        result=result,
    )

    if batch_column:
        batches = metadata[batch_column]
        normalized = batches.astype(str).str.strip()
        invalid_batch = batches.isna() | normalized.str.lower().isin(_EMPTY_BATCH_VALUES)
        if invalid_batch.any():
            count = int(invalid_batch.sum())
            result.repairable_issues.append(
                f"{count} empty batch value(s) will be replaced with '0'."
            )
            for sample_id in batches.index[invalid_batch]:
                result.repaired_cells.append(
                    {
                        "table": "metadata",
                        "row": str(sample_id),
                        "column": batch_column,
                        "replacement": "0",
                    }
                )
            normalized = normalized.mask(invalid_batch, "0")
        result.batches = normalized

    zero_rows = result.counts.sum(axis=1).eq(0)
    if zero_rows.all() and not zero_rows.empty:
        result.hard_errors.append("All sample rows have zero total reads.")
    elif zero_rows.any():
        ids = result.counts.index[zero_rows].astype(str).tolist()
        result.repairable_issues.append(
            f"{len(ids)} sample row(s) have zero total reads: "
            + ", ".join(ids[:5])
            + (", ..." if len(ids) > 5 else "")
        )

    if not result.concentrations.empty and result.concentrations.eq(0).all():
        result.hard_errors.append(
            "All concentration values are zero after invalid values are replaced."
        )

    if result.repairable_issues and not repair:
        return result

    if batch_column:
        result.metadata_matrix = np.column_stack(
            [
                result.concentrations.to_numpy(dtype=float),
                result.batches.to_numpy(dtype=object),
            ]
        )
    else:
        result.metadata_matrix = result.concentrations.to_numpy(dtype=float).reshape(
            -1, 1
        )
    return result


def _numeric_table(
    table: pd.DataFrame,
    *,
    table_name: str,
    repair: bool,
    result: ConcentrationCheckResult,
) -> pd.DataFrame:
    numeric = table.apply(pd.to_numeric, errors="coerce")
    values = numeric.to_numpy(dtype=float)
    invalid = numeric.isna() | ~np.isfinite(values) | (numeric < 0)
    count = int(invalid.to_numpy().sum())
    if count:
        result.repairable_issues.append(
            f"{count} empty, non-numeric, non-finite, or negative {table_name} "
            "cell(s) will be replaced with 0."
        )
        rows, columns = np.where(invalid.to_numpy())
        for row, column in zip(rows, columns):
            result.repaired_cells.append(
                {
                    "table": table_name,
                    "row": str(table.index[row]),
                    "column": str(table.columns[column]),
                    "replacement": "0",
                }
            )
        numeric = numeric.mask(invalid, 0.0)
    return numeric.astype(float)


def _numeric_series(
    series: pd.Series,
    *,
    column_name: str,
    repair: bool,
    result: ConcentrationCheckResult,
) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").astype(float)
    invalid = numeric.isna() | ~np.isfinite(numeric.to_numpy()) | (numeric < 0)
    count = int(invalid.sum())
    if count:
        result.repairable_issues.append(
            f"{count} empty, non-numeric, non-finite, or negative concentration "
            "value(s) will be replaced with 0."
        )
        for sample_id in series.index[invalid]:
            result.repaired_cells.append(
                {
                    "table": "metadata",
                    "row": str(sample_id),
                    "column": column_name,
                    "replacement": "0",
                }
            )
        numeric = numeric.mask(invalid, 0.0)
    return numeric.astype(float)
