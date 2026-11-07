from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import pandas as pd

from dmcscrub_app.core.validation import InputValidationError


def read_count_table(path: str | Path) -> pd.DataFrame:
    _validate_count_header(path)
    counts = pd.read_csv(path, index_col=0)
    _validate_sample_ids(counts.index)
    counts.index = counts.index.astype(str)
    return counts


def _validate_count_header(path: str | Path) -> None:
    """Validate the raw CSV shape and IDs before pandas normalizes either one."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next((row for row in reader if row), None)
        if header is None:
            return
        expected_columns = len(header)
        mismatched_rows: list[int] = []
        for row in reader:
            if not row:
                continue
            if len(row) != expected_columns:
                mismatched_rows.append(reader.line_num)

    if mismatched_rows:
        details = ", ".join(str(line_number) for line_number in mismatched_rows[:10])
        if len(mismatched_rows) > 10:
            details += ", ..."
        raise InputValidationError(
            "Count CSV data rows must have the same number of columns as the header. "
            f"Affected rows: {details}."
        )

    feature_ids = [str(value).strip() for value in header[1:]]
    if any(not feature_id for feature_id in feature_ids):
        raise InputValidationError(
            "Feature IDs must be non-empty and unique. Empty feature ID(s) found."
        )

    counts = Counter(feature_ids)
    duplicates = [feature_id for feature_id, count in counts.items() if count > 1]
    if duplicates:
        listed = ", ".join(duplicates[:5])
        if len(duplicates) > 5:
            listed += ", ..."
        raise InputValidationError(
            f"Feature IDs must be non-empty and unique. Duplicate feature ID(s): {listed}"
        )


def read_metadata_table(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def _validate_sample_ids(values: pd.Index | pd.Series) -> None:
    if any(pd.isna(value) or not str(value).strip() for value in values):
        raise InputValidationError(
            "The Sample file or Metadata file contains an empty Sample ID."
        )
