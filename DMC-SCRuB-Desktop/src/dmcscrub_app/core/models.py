from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

C_SCRUB_STEP_COLUMN = "All samples"
C_SCRUB_STEP_VALUE = "1"


@dataclass(frozen=True)
class InputData:
    counts: pd.DataFrame
    metadata: pd.DataFrame
