"""Pure view models for the UI layer.

These dataclasses are intentionally free of any Qt or backend dependency so
that both the mock data provider and the future real backend can produce them.
They describe *what* the UI renders, never *how* the data is computed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dmcscrub_app.core.models import InputData


ALGORITHM_C_SCRUB = "C-SCRuB"
ALGORITHM_DMC_SCRUB = "DMC-SCRuB"


@dataclass(frozen=True)
class ColumnMapping:
    """User-selected metadata columns (chosen in the startup dialog)."""

    sample: str
    concentration: str = ""
    batch: str = ""
    label: str = ""
    positive_value: str = ""


@dataclass(frozen=True)
class DatasetConfig:
    """Everything needed to identify and load one dataset (one tab)."""

    name: str
    count_path: Path
    metadata_path: Path
    mapping: ColumnMapping
    algorithm: str = ALGORITHM_C_SCRUB


@dataclass(frozen=True)
class MetricRow:
    """A single label/value line inside an Input Summary card."""

    label: str
    value: str


@dataclass(frozen=True)
class InputFile:
    """One entry in the 'Input Files' card, with a validity flag."""

    name: str
    ok: bool = True


@dataclass(frozen=True)
class InputSummaryVM:
    """View model backing the left-hand Input Summary panel."""

    samples: list[MetricRow] = field(default_factory=list)
    controls: list[MetricRow] = field(default_factory=list)
    features: list[MetricRow] = field(default_factory=list)
    files: list[InputFile] = field(default_factory=list)


@dataclass(frozen=True)
class PipelineStep:
    """One node in the processing pipeline."""

    key: str
    title: str
    sample_count: int
    control_groups: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PipelineVM:
    """View model backing the middle DAG and the right control config."""

    total_samples: int
    steps: list[PipelineStep]
    all_control_groups: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConcentrationEntry:
    sample_name: str
    concentration: float


@dataclass(frozen=True)
class DatasetVM:
    """Aggregate view model for a single dataset tab."""

    config: DatasetConfig
    summary: InputSummaryVM
    pipeline: PipelineVM
    # Loaded backend data, needed to (re)build the real workflow DAG. Optional so
    # the mock provider (which has no real tables) can still produce a VM.
    input_data: "InputData | None" = None
    concentrations: list[ConcentrationEntry] = field(default_factory=list)
