"""Every type that crosses the process boundary, plus its JSON encoding.

Plain dataclasses: no Qt, no torch, no pandas. The parent process builds a
`BackendRunRequest`, the child reads it back and streams `Event` lines home.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 8

ALGORITHM_C_SCRUB = "C-SCRuB"
ALGORITHM_DMC_SCRUB = "DMC-SCRuB"
ALGORITHMS = (
    ALGORITHM_C_SCRUB,
    ALGORITHM_DMC_SCRUB,
)


class SchemaVersionError(ValueError):
    """Request or manifest written by an incompatible version."""


@dataclass(frozen=True)
class ColumnMapping:
    sample_name: str
    concentration: str = ""
    batch: str = ""
    label: str = ""
    positive_value: str = ""


@dataclass(frozen=True)
class BackendRunRequest:
    dataset_name: str
    count_path: Path
    metadata_path: Path
    column_mapping: ColumnMapping
    run_dir: Path
    algorithm: str
    repair_invalid: bool = False
    schema_version: int = SCHEMA_VERSION

    def to_json(self) -> str:
        return json.dumps(_encode(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> BackendRunRequest:
        raw = json.loads(text)
        version = raw.get("schema_version")
        if version != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Run request schema version {version!r} != {SCHEMA_VERSION}"
            )
        algorithm = raw.get("algorithm")
        if algorithm not in ALGORITHMS:
            raise ValueError(f"Unknown run algorithm: {algorithm!r}")
        return cls(
            dataset_name=raw["dataset_name"],
            count_path=Path(raw["count_path"]),
            metadata_path=Path(raw["metadata_path"]),
            column_mapping=ColumnMapping(**raw["column_mapping"]),
            run_dir=Path(raw["run_dir"]),
            algorithm=algorithm,
            repair_invalid=bool(raw.get("repair_invalid", False)),
            schema_version=version,
        )


@dataclass(frozen=True)
class BackendRunResult:
    run_dir: Path
    manifest_path: Path


# --- events -----------------------------------------------------------------
# One JSON object per line on stderr.

STAGE_LOADING = "loading"
STAGE_BUILDING_INPUTS = "building_inputs"
STAGE_FITTING = "fitting"
STAGE_SAVING = "saving"
STAGES = (STAGE_LOADING, STAGE_BUILDING_INPUTS, STAGE_FITTING, STAGE_SAVING)

EVENT_STAGE = "stage"
EVENT_NOTICE = "notice"
EVENT_WARNING = "warning"
EVENT_FINISHED = "finished"
EVENT_FAILED = "failed"


class EventSink:
    """Writes events as JSON Lines. `stream` is stderr in the child process."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    def emit(self, event_type: str, **payload: Any) -> None:
        line = json.dumps({"type": event_type, **payload}, default=_json_default)
        self._stream.write(line + "\n")
        self._stream.flush()

    def stage(self, value: str) -> None:
        self.emit(EVENT_STAGE, value=value)

    def notice(self, text: str) -> None:
        self.emit(EVENT_NOTICE, text=text)

    def warning(self, text: str) -> None:
        self.emit(EVENT_WARNING, text=text)

    def finished(self, manifest_path: Path) -> None:
        self.emit(EVENT_FINISHED, manifest=str(manifest_path))

    def failed(self, message: str) -> None:
        self.emit(EVENT_FAILED, message=message)


class NullEventSink(EventSink):
    """For tests and scripts that call the runner directly."""

    def __init__(self) -> None:  # noqa: D107 - deliberately drops the stream
        super().__init__(None)

    def emit(self, event_type: str, **payload: Any) -> None:
        return


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialise {type(value).__name__}")


def _encode(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {key: _encode(item) for key, item in asdict(value).items()}
    return value
