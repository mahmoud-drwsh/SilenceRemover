"""Shared typing and result contracts for ffmpeg helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ExecutionMode = Literal["run", "run_with_progress"]


@dataclass(frozen=True)
class RunnerOptions:
    """Execution options for ffmpeg runner helpers."""

    check: bool = True
    capture_output: bool = False
    execution_mode: ExecutionMode = "run"
