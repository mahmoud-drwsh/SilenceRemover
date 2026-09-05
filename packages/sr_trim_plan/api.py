"""Trim planning policy shared by snippet and final render flows."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Callable, Literal, Optional

from src.core.constants import (
    NATURAL_TARGET_NOISE_THRESHOLD_DB,
    NATURAL_TARGET_MIN_SILENCE_SEC,
    EDGE_RESCAN_MIN_DURATION_SEC,
    EDGE_RESCAN_THRESHOLD_DB,
    EDGE_SILENCE_KEEP_SEC,
    TARGET_SEARCH_BASE_PADDING_SEC,
    TARGET_SEARCH_HIGH_DB,
    TARGET_SEARCH_LOW_DB,
    TARGET_SEARCH_MIN_SILENCE_LEN_SEC,
    TARGET_SEARCH_PADDING_STEP_SEC,
    TARGET_SEARCH_STEP_DB,
    TRIM_TIMESTAMP_EPSILON_SEC,
    TrimDefaults,
    resolve_trim_defaults,
)
from src.ffmpeg.probing import probe_duration
from src.media.silence_detector import (
    build_keep_segments_from_silences,
    normalize_timestamp,
)
from sr_silence_detection import (
    detect_silence_with_edges,
    detect_silence,
)

from sr_trim_plan.pause_budget import (
    NATURAL_PAUSE_POLICY_VERSION, PausePolicy, allocate_pause_budget,
)

TrimPlanMode = Literal["target", "non_target"]
_LengthEstimator = Callable[[float], Optional[float]]


@dataclass(frozen=True)
class TrimPlan:
    """Resolved trim strategy and segment output for one media run."""

    mode: TrimPlanMode
    segments_to_keep: list[tuple[float, float]]
    input_duration_sec: float
    resulting_length_sec: float
    resolved_noise_threshold: float
    resolved_min_duration: float
    resolved_pad_sec: float
    target_length: Optional[float]
    should_copy_input: bool = False
    policy_version: str | None = None
    minimum_length_sec: float | None = None
    planning_budget_sec: float | None = None


def _probe_and_validate_duration(input_file: Path) -> float:
    duration_sec = probe_duration(input_file)
    if not math.isfinite(duration_sec) or duration_sec <= 0:
        raise ValueError(f"Invalid video duration: {duration_sec}s. Video file may be corrupted or empty.")
    return normalize_timestamp(duration_sec)


def _threshold_grid_count(
    *,
    low_db: float = TARGET_SEARCH_LOW_DB,
    high_db: float = TARGET_SEARCH_HIGH_DB,
    step_db: float = TARGET_SEARCH_STEP_DB,
) -> int:
    return int(round((high_db - low_db) / step_db)) + 1


def _threshold_from_index(
    index: int,
    *,
    low_db: float = TARGET_SEARCH_LOW_DB,
    step_db: float = TARGET_SEARCH_STEP_DB,
) -> float:
    return round(low_db + index * step_db, 3)


def _padding_from_offset(
    base_padding_sec: float,
    offset_index: int,
    *,
    padding_step_sec: float = TARGET_SEARCH_PADDING_STEP_SEC,
) -> float:
    return round(base_padding_sec + offset_index * padding_step_sec, 3)


def binary_search_threshold(
    *,
    target_length: float,
    estimate_length: _LengthEstimator,
    low_db: float = TARGET_SEARCH_LOW_DB,
    high_db: float = TARGET_SEARCH_HIGH_DB,
    step_db: float = TARGET_SEARCH_STEP_DB,
    epsilon_sec: float = TRIM_TIMESTAMP_EPSILON_SEC,
) -> tuple[float, bool]:
    """Return the earliest threshold on the discrete grid that keeps output at or under target."""
    low_idx = 0
    high_idx = _threshold_grid_count(low_db=low_db, high_db=high_db, step_db=step_db) - 1
    best_idx: int | None = None

    while low_idx <= high_idx:
        mid_idx = (low_idx + high_idx) // 2
        threshold_db = _threshold_from_index(mid_idx, low_db=low_db, step_db=step_db)
        estimated_length = estimate_length(threshold_db)

        if estimated_length is not None and estimated_length <= target_length + epsilon_sec:
            best_idx = mid_idx
            high_idx = mid_idx - 1
        else:
            low_idx = mid_idx + 1

    if best_idx is None:
        return _threshold_from_index(
            _threshold_grid_count(low_db=low_db, high_db=high_db, step_db=step_db) - 1,
            low_db=low_db,
            step_db=step_db,
        ), False

    return _threshold_from_index(best_idx, low_db=low_db, step_db=step_db), True


def binary_search_padding(
    *,
    target_length: float,
    duration_sec: float,
    estimate_length: _LengthEstimator,
    base_padding_sec: float = TARGET_SEARCH_BASE_PADDING_SEC,
    padding_step_sec: float = TARGET_SEARCH_PADDING_STEP_SEC,
    epsilon_sec: float = TRIM_TIMESTAMP_EPSILON_SEC,
) -> float:
    """Return the largest padding on the discrete grid that stays at or under target."""
    base_padding_sec = round(base_padding_sec, 3)
    max_offset_idx = max(
        0,
        int(max(0.0, round(duration_sec, 3) - base_padding_sec) / padding_step_sec + 1e-9),
    )

    base_length = estimate_length(base_padding_sec)
    if base_length is None or base_length > target_length + epsilon_sec:
        return base_padding_sec

    valid_offset_idx = 0
    current_offset_idx = 1
    upper_bound_offset_idx: int | None = None

    while current_offset_idx <= max_offset_idx:
        pad_sec = _padding_from_offset(
            base_padding_sec,
            current_offset_idx,
            padding_step_sec=padding_step_sec,
        )
        estimated_length = estimate_length(pad_sec)

        if estimated_length is None or estimated_length > target_length + epsilon_sec:
            upper_bound_offset_idx = current_offset_idx
            break

        valid_offset_idx = current_offset_idx
        if current_offset_idx == max_offset_idx:
            return _padding_from_offset(
                base_padding_sec,
                valid_offset_idx,
                padding_step_sec=padding_step_sec,
            )
        current_offset_idx = min(max_offset_idx, current_offset_idx * 2)

    if upper_bound_offset_idx is None or valid_offset_idx >= upper_bound_offset_idx:
        return _padding_from_offset(
            base_padding_sec,
            valid_offset_idx,
            padding_step_sec=padding_step_sec,
        )

    low_offset_idx = valid_offset_idx
    high_offset_idx = upper_bound_offset_idx - 1

    while low_offset_idx < high_offset_idx:
        mid_offset_idx = (low_offset_idx + high_offset_idx + 1) // 2
        pad_sec = _padding_from_offset(
            base_padding_sec,
            mid_offset_idx,
            padding_step_sec=padding_step_sec,
        )
        estimated_length = estimate_length(pad_sec)

        if estimated_length is not None and estimated_length <= target_length + epsilon_sec:
            valid_offset_idx = mid_offset_idx
            low_offset_idx = mid_offset_idx
        else:
            high_offset_idx = mid_offset_idx - 1

    return _padding_from_offset(
        base_padding_sec,
        valid_offset_idx,
        padding_step_sec=padding_step_sec,
    )


def build_trim_plan(
    input_file: Path,
    target_length: Optional[float],
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    temp_dir: Optional[Path] = None,
) -> TrimPlan:
    """Resolve mode policy and return a reusable trim plan."""
    trim_defaults = resolve_trim_defaults(
        target_length=target_length,
        noise_threshold=noise_threshold,
        min_duration=min_duration,
        pad_sec=pad_sec,
    )
    duration_sec = _probe_and_validate_duration(input_file)
    if target_length is None:
        return _build_non_target_trim_plan(input_file=input_file, duration_sec=duration_sec, trim_defaults=trim_defaults)

    return _build_target_trim_plan(
        input_file=input_file,
        temp_dir=temp_dir,
        duration_sec=duration_sec,
        target_length=target_length,
    )


def _build_non_target_trim_plan(
    input_file: Path,
    duration_sec: float,
    trim_defaults: TrimDefaults,
) -> TrimPlan:
    """Build a non-target trim plan."""
    silence_starts, silence_ends = detect_silence_with_edges(
        input_file=input_file,
        primary_noise_threshold=trim_defaults.noise_threshold,
        primary_min_duration=trim_defaults.min_duration,
        edge_noise_threshold=EDGE_RESCAN_THRESHOLD_DB,
        edge_min_duration=EDGE_RESCAN_MIN_DURATION_SEC,
        edge_keep_seconds=EDGE_SILENCE_KEEP_SEC,
    )
    segments_to_keep = build_keep_segments_from_silences(
        silence_starts=silence_starts,
        silence_ends=silence_ends,
        duration_sec=duration_sec,
        pad_sec=trim_defaults.pad_sec,
    )
    resulting_length = normalize_timestamp(sum(end - start for start, end in segments_to_keep))
    return TrimPlan(
        mode="non_target",
        segments_to_keep=segments_to_keep,
        input_duration_sec=duration_sec,
        resulting_length_sec=resulting_length,
        resolved_noise_threshold=trim_defaults.noise_threshold,
        resolved_min_duration=trim_defaults.min_duration,
        resolved_pad_sec=trim_defaults.pad_sec,
        target_length=None,
    )


def _build_target_trim_plan(
    input_file: Path,
    temp_dir: Optional[Path],
    duration_sec: float,
    target_length: float,
) -> TrimPlan:
    """Budget detected pauses without making speech detection more aggressive."""
    policy = PausePolicy()
    if not math.isfinite(target_length) or target_length <= policy.render_margin_sec:
        raise ValueError("Target must be finite and greater than render margin")
    # Raw intervals are required: legacy edge normalization already subtracts
    # silence and cannot represent the actual pause lengths needed by this policy.
    silence_starts, silence_ends = detect_silence(
        input_file=input_file,
        noise_threshold=NATURAL_TARGET_NOISE_THRESHOLD_DB,
        min_duration=NATURAL_TARGET_MIN_SILENCE_SEC,
    )
    allocation = allocate_pause_budget(
        duration_sec, silence_starts, silence_ends, target_length, policy,
    )
    return TrimPlan(
        mode="target",
        segments_to_keep=allocation.segments,
        input_duration_sec=duration_sec,
        resulting_length_sec=allocation.resulting_length_sec,
        resolved_noise_threshold=NATURAL_TARGET_NOISE_THRESHOLD_DB,
        resolved_min_duration=NATURAL_TARGET_MIN_SILENCE_SEC,
        # Compatibility metadata: minimum retained sound per side of an edited
        # internal pause, not a uniform padding applied to every segment.
        resolved_pad_sec=policy.min_gap_sec / 2,
        target_length=target_length,
        should_copy_input=allocation.segments == [(0.0, duration_sec)],
        policy_version=NATURAL_PAUSE_POLICY_VERSION,
        minimum_length_sec=allocation.minimum_length_sec,
        planning_budget_sec=allocation.budget_sec,
    )
