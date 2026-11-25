from __future__ import annotations

import pandas as pd


class InputValidationError(ValueError):
    """Raised when uploaded concentration-workflow inputs are invalid."""


def parse_is_control(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series

    normalized = series.astype(str).str.strip().str.lower()
    true_values = {"true", "t", "1", "yes", "y"}
    false_values = {"false", "f", "0", "no", "n"}

    invalid = normalized[~normalized.isin(true_values | false_values)]
    if not invalid.empty:
        examples = ", ".join(invalid.head(5).astype(str).tolist())
        raise InputValidationError(f"Cannot parse is_control values: {examples}")

    return normalized.isin(true_values)
