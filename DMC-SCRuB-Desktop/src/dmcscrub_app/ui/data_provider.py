"""Data source seam for the UI.

`DatasetProvider` turns file paths into the view models a dataset tab renders. It
does not run anything: a run goes through `RunController` and a child process.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from dmcscrub_app.ui.models import (
    ALGORITHM_C_SCRUB,
    ALGORITHM_DMC_SCRUB,
    ConcentrationEntry,
    DatasetConfig,
    DatasetVM,
    InputFile,
    InputSummaryVM,
    MetricRow,
    PipelineStep,
    PipelineVM,
)


class DatasetProvider(ABC):
    """Turns a `DatasetConfig` into a fully populated `DatasetVM`."""

    @abstractmethod
    def read_metadata_columns(self, metadata_path: Path) -> list[str]:
        """Return the column names of a metadata table (for the dropdowns)."""

    @abstractmethod
    def build_dataset(self, config: DatasetConfig) -> DatasetVM:
        """Assemble the view model shown in a dataset tab."""


def _compact_reads(value: float) -> str:
    value = float(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} M"
    if value >= 1_000:
        return f"{value / 1_000:.1f} K"
    return f"{int(value)}"


class RealDatasetProvider(DatasetProvider):
    """Loads the actual count/metadata tables and derives the real view models."""

    def read_metadata_columns(self, metadata_path: Path) -> list[str]:
        import pandas as pd

        header = pd.read_csv(metadata_path, nrows=0)
        # First column is the index (sample id); the rest are selectable columns.
        return [str(col) for col in header.columns]

    def build_dataset(self, config: DatasetConfig) -> DatasetVM:
        if config.algorithm not in (ALGORITHM_C_SCRUB, ALGORITHM_DMC_SCRUB):
            raise ValueError(f"Unsupported algorithm: {config.algorithm!r}")
        return self._build_concentration_dataset(config)

    def _build_concentration_dataset(self, config: DatasetConfig) -> DatasetVM:
        import pandas as pd

        from dmcscrub_app.backend.cscrub_checker import check_cscrub_inputs
        from dmcscrub_app.backend.dmcscrub_checker import check_dmcscrub_inputs
        from dmcscrub_app.core.models import (
            C_SCRUB_STEP_COLUMN,
            C_SCRUB_STEP_VALUE,
            InputData,
        )
        from dmcscrub_app.core.validation import InputValidationError

        if config.algorithm == ALGORITHM_C_SCRUB:
            checked = check_cscrub_inputs(
                config.count_path,
                config.metadata_path,
                sample_column=config.mapping.sample,
                concentration_column=config.mapping.concentration,
                repair=True,
            )
        else:
            checked = check_dmcscrub_inputs(
                config.count_path,
                config.metadata_path,
                sample_column=config.mapping.sample,
                concentration_column=config.mapping.concentration,
                batch_column=config.mapping.batch,
                repair=True,
            )
        if checked.hard_errors:
            raise InputValidationError("\n".join(checked.hard_errors))

        numeric_counts = checked.counts
        metadata = pd.DataFrame(index=numeric_counts.index)
        metadata.index.name = config.mapping.sample
        metadata["is_control"] = False
        metadata["Groups"] = "sample"
        metadata["__concentration__"] = checked.concentrations.to_numpy(dtype=float)

        if config.algorithm == ALGORITHM_C_SCRUB:
            step_column = C_SCRUB_STEP_COLUMN
            metadata[step_column] = C_SCRUB_STEP_VALUE
        else:
            step_column = config.mapping.batch
            assert checked.batches is not None
            metadata[step_column] = checked.batches.to_numpy()
        input_data = InputData(counts=numeric_counts, metadata=metadata)

        total_samples = int(numeric_counts.shape[0])
        total_reads = float(numeric_counts.to_numpy().sum())
        summary = InputSummaryVM(
            samples=[
                MetricRow("Total samples", f"{total_samples:,}"),
                MetricRow("Total reads", _compact_reads(total_reads)),
                MetricRow(
                    "Avg. reads / sample",
                    f"{int(total_reads // max(total_samples, 1)):,}",
                ),
            ],
            controls=[MetricRow("Required by algorithm", "No")],
            features=[
                MetricRow("Total taxa (ASVs)", f"{numeric_counts.shape[1]:,}"),
                MetricRow(
                    "Non-zero taxa",
                    f"{int((numeric_counts.sum(axis=0) > 0).sum()):,}",
                ),
                MetricRow("Total samples", f"{total_samples:,}"),
            ],
            files=[
                InputFile(config.count_path.name, ok=True),
                InputFile(config.metadata_path.name, ok=True),
            ],
        )
        pipeline = PipelineVM(
            total_samples=total_samples,
            steps=[
                PipelineStep(
                    key=step_column,
                    title=step_column,
                    sample_count=total_samples,
                )
            ],
        )
        concentration_entries = [
            ConcentrationEntry(
                sample_name=str(sample_name),
                concentration=float(metadata.at[sample_name, "__concentration__"]),
            )
            for sample_name in numeric_counts.index
        ]
        return DatasetVM(
            config=config,
            summary=summary,
            pipeline=pipeline,
            input_data=input_data,
            concentrations=concentration_entries,
        )
