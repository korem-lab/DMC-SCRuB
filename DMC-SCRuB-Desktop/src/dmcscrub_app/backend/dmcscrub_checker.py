"""DMC-SCRuB input checker."""

from __future__ import annotations

from pathlib import Path

from dmcscrub_app.backend.concentration_check import (
    ConcentrationCheckResult,
    check_concentration_inputs,
)


def check_dmcscrub_inputs(
    count_path: Path,
    metadata_path: Path,
    *,
    sample_column: str,
    concentration_column: str,
    batch_column: str,
    label_column: str,
    positive_value: str,
    repair: bool = False,
) -> ConcentrationCheckResult:
    checked = check_concentration_inputs(
        count_path,
        metadata_path,
        sample_column=sample_column,
        concentration_column=concentration_column,
        batch_column=batch_column,
        label_column=label_column,
        positive_value=positive_value,
        repair=repair,
    )
    if (
        checked.hard_errors
        or checked.batches is None
        or checked.labels is None
    ):
        return checked
    unique_batches = checked.batches.drop_duplicates().tolist()
    if len(unique_batches) < 2:
        checked.hard_errors.append(
            "DMC-SCRuB needs at least two batches so one can be held out for testing."
        )
        return checked

    test_batch = unique_batches[-1]
    training_count = int(checked.batches.ne(test_batch).sum())
    if training_count < 10:
        checked.hard_errors.append(
            "DMC-SCRuB needs at least 10 training samples outside the held-out "
            f"test batch {test_batch!r}."
        )

    training_mask = checked.batches.ne(test_batch)
    positive_count = int(checked.labels.loc[training_mask].sum())
    negative_count = training_count - positive_count
    if positive_count == 0 or negative_count == 0:
        checked.hard_errors.append(
            "DMC-SCRuB training data must contain both classes after holding "
            f"out test batch {test_batch!r}. Positive class {positive_value!r}: "
            f"{positive_count} sample(s); negative class: {negative_count} sample(s)."
        )

    for batch in unique_batches:
        in_batch = checked.batches.eq(batch)
        sample_count = int(in_batch.sum())
        if sample_count < 2:
            checked.hard_errors.append(
                f"Batch {batch!r} needs at least two samples for DMC-SCRuB."
            )
        elif checked.counts.loc[in_batch].to_numpy().sum() == 0:
            checked.hard_errors.append(
                f"Batch {batch!r} has no positive read counts."
            )
        elif checked.concentrations.loc[in_batch].nunique() < 2:
            checked.hard_errors.append(
                f"Batch {batch!r} needs at least two distinct concentration values."
            )
    return checked
