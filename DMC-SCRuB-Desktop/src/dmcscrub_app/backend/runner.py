"""Orchestration of one C-SCRuB or DMC-SCRuB run."""

from __future__ import annotations

from datetime import datetime

from dmcscrub_app.backend.contracts import (
    ALGORITHM_C_SCRUB,
    ALGORITHM_DMC_SCRUB,
    STAGE_LOADING,
    BackendRunRequest,
    BackendRunResult,
    EventSink,
)
from dmcscrub_app.backend.cscrub_runner import run_cscrub
from dmcscrub_app.backend.dmcscrub_runner import run_dmcscrub


def run_backend(request: BackendRunRequest, events: EventSink) -> BackendRunResult:
    created_at = datetime.now()

    events.stage(STAGE_LOADING)
    if request.algorithm == ALGORITHM_C_SCRUB:
        return run_cscrub(request, events, created_at=created_at)
    if request.algorithm == ALGORITHM_DMC_SCRUB:
        return run_dmcscrub(request, events, created_at=created_at)
    raise ValueError(f"Unknown run algorithm: {request.algorithm!r}")
