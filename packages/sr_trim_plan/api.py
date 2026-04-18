"""Trim planning policy shared by snippet and final render flows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from src.core.constants import (
    EDGE_RESCAN_MIN_DURATION_SEC,
    EDGE_RESCAN_THRESHOLD_DB,
    EDGE_SILENCE_KEEP_SEC,
    TRIM_TIMESTAMP_EPSILON_SEC,
    TrimDefaults,
    resolve_trim_defaults,
)
from src.ffmpeg.probing import probe_duration
from src.media.silence_detector import (
    build_keep_segments_from_silences,
    calculate_resulting_length,
    normalize_timestamp,
)
from sr_silence_detection import (
    detect_silence_with_edges,  # Keep for non-target mode
    detect_edge_only_cached,     # NEW
    detect_primary_with_cached_edges,  # NEW
)
from sr_threshold_selection import find_optimal_padding

TrimPlanMode = Literal["target", "non_target"]

# Binary search constants for target mode
# 50 tiers from 0.5s to 0.01s in 0.01s steps
_MIN_DURATIONS_TIERS = [0.5 - i * 0.01 for i in range(50)]  # 0.5, 0.49, ..., 0.01
_DB_SEARCH_LOW = -60.0
_DB_SEARCH_HIGH = -25.0
_DB_SEARCH_STEP = 0.05


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


def should_copy_when_target_exceeds_input(duration_sec: float, target_length: Optional[float]) -> bool:
    """Return True when target mode can skip trimming because input is already short enough."""
    return target_length is not None and target_length >= duration_sec - TRIM_TIMESTAMP_EPSILON_SEC


def _probe_and_validate_duration(input_file: Path) -> float:
    duration_sec = probe_duration(input_file)
    if duration_sec <= 0:
        raise ValueError(f"Invalid video duration: {duration_sec}s. Video file may be corrupted or empty.")
    return normalize_timestamp(duration_sec)


def build_trim_plan(
    input_file: Path,
    target_length: Optional[float],
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    temp_dir: Optional[Path] = None,  # NEW parameter for cached edge detection (target mode only)
) -> TrimPlan:
    """Resolve mode policy and return a reusable trim plan."""
    trim_defaults = resolve_trim_defaults(
        target_length=target_length,
        noise_threshold=noise_threshold,
        min_duration=min_duration,
        pad_sec=pad_sec,
    )
    duration_sec = _probe_and_validate_duration(input_file)
    if should_copy_when_target_exceeds_input(duration_sec, target_length):
        return TrimPlan(
            mode="target",
            segments_to_keep=[(0.0, normalize_timestamp(duration_sec))],
            input_duration_sec=duration_sec,
            resulting_length_sec=duration_sec,
            resolved_noise_threshold=trim_defaults.noise_threshold,
            resolved_min_duration=trim_defaults.min_duration,
            resolved_pad_sec=0.0,
            target_length=target_length,
            should_copy_input=True,
        )

    if target_length is None:
        return _build_non_target_trim_plan(input_file=input_file, duration_sec=duration_sec, trim_defaults=trim_defaults)

    return _build_target_trim_plan(
        input_file=input_file,
        temp_dir=temp_dir,  # NEW
        duration_sec=duration_sec,
        target_length=target_length,
        trim_defaults=trim_defaults,
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


def _collect_threshold_candidates_binary(
    input_file: Path,
    temp_dir: Path,
    basename: str,
    duration_sec: float,
    target_length: float,
    edge_starts: list[float],
    edge_ends: list[float],
) -> tuple[list[float], list[float], float, float, float]:
    """Binary search for optimal (min_duration, dB) combination.

    Optimality criteria:
    - Maximize min_duration (longer gaps preserved)
    - Minimize dB (quieter threshold = more natural audio)
    - Constraint: result_length <= target_length

    Search space:
    - Min durations: 17 tiers from 0.5s to 0.1s in 0.025s steps
    - dB range: -60.0 to -30.0 in 0.25dB steps (121 values)

    Algorithm:
    - For each min_duration (longest first), binary search dB to find
      the quietest threshold that satisfies target_length constraint
    - Early termination: return at first tier where a valid dB is found
    - Cache all detection attempts (handled by detect_primary_with_cached_edges)

    Returns:
        Tuple of (silence_starts, silence_ends, chosen_min_dur, chosen_dB, pad_sec)
    """
    for min_dur_raw in _MIN_DURATIONS_TIERS:  # Try longest first
        min_dur = round(min_dur_raw, 3)
        # Binary search dB at this min_dur
        low_db, high_db = _DB_SEARCH_LOW, _DB_SEARCH_HIGH
        best_db = None
        best_starts, best_ends = None, None

        while low_db <= high_db:
            mid_db = round((low_db + high_db) / 2, 3)

            # Detect with (min_dur, mid_db)
            silence_starts, silence_ends = detect_primary_with_cached_edges(
                input_file=input_file,
                primary_noise_threshold=mid_db,
                primary_min_duration=min_dur,
                edge_starts=edge_starts,
                edge_ends=edge_ends,
                edge_keep_seconds=EDGE_SILENCE_KEEP_SEC,
                duration_sec=duration_sec,
                temp_dir=temp_dir,
                basename=basename,
            )

            # Calculate base trimmed length
            base_length = calculate_resulting_length(
                silence_starts, silence_ends, duration_sec, 0.0
            )

            if base_length <= target_length:
                # This works, try quieter (better quality)
                best_db = mid_db
                best_starts, best_ends = silence_starts, silence_ends
                high_db = round(mid_db - _DB_SEARCH_STEP, 3)
            else:
                # Doesn't work, need louder (more aggressive)
                low_db = round(mid_db + _DB_SEARCH_STEP, 3)

        if best_db is not None:
            # Found optimal at this min_dur!
            # Now compute optimal padding
            pad_sec = find_optimal_padding(
                best_starts, best_ends, duration_sec, target_length
            )
            return (best_starts, best_ends, min_dur, best_db, pad_sec)

    # Fallback: most aggressive settings (no truncation - accept over-target)
    # Use min_dur=0.01, dB=-25.0
    silence_starts, silence_ends = detect_primary_with_cached_edges(
        input_file=input_file,
        primary_noise_threshold=_DB_SEARCH_HIGH,  # -25.0
        primary_min_duration=_MIN_DURATIONS_TIERS[-1],  # 0.01
        edge_starts=edge_starts,
        edge_ends=edge_ends,
        edge_keep_seconds=EDGE_SILENCE_KEEP_SEC,
        duration_sec=duration_sec,
        temp_dir=temp_dir,
        basename=basename,
    )
    return (silence_starts, silence_ends, _MIN_DURATIONS_TIERS[-1], _DB_SEARCH_HIGH, 0.0)


def _build_target_trim_plan(
    input_file: Path,
    temp_dir: Path,  # NEW parameter
    duration_sec: float,
    target_length: float,
    trim_defaults: TrimDefaults,
) -> TrimPlan:
    """Build a target-mode trim plan with binary search for optimal threshold/padding policy."""
    # Derive basename from input file for cache naming
    basename = input_file.stem

    # Step 1: Run edge detection ONCE (cached) with pre-probed duration
    edge_starts, edge_ends = detect_edge_only_cached(
        input_file, temp_dir, basename,
        EDGE_RESCAN_THRESHOLD_DB, EDGE_RESCAN_MIN_DURATION_SEC, EDGE_SILENCE_KEEP_SEC,
        duration_sec=duration_sec
    )

    # Step 2: Binary search for optimal (min_duration, dB) combination
    silence_starts, silence_ends, chosen_min_dur, chosen_db, pad_sec = _collect_threshold_candidates_binary(
        input_file=input_file,
        temp_dir=temp_dir,
        basename=basename,
        duration_sec=duration_sec,
        target_length=target_length,
        edge_starts=edge_starts,
        edge_ends=edge_ends,
    )

    # Step 3: Build segments with chosen padding
    segments_to_keep = build_keep_segments_from_silences(
        silence_starts=silence_starts,
        silence_ends=silence_ends,
        duration_sec=duration_sec,
        pad_sec=pad_sec,
    )
    resulting_length = normalize_timestamp(sum(end - start for start, end in segments_to_keep))

    # Note: No truncation - we accept over-target results to preserve all content

    # Determine if we used most aggressive settings
    used_most_aggressive = (
        chosen_min_dur == _MIN_DURATIONS_TIERS[-1] and chosen_db == _DB_SEARCH_HIGH
    )

    return TrimPlan(
        mode="target",
        segments_to_keep=segments_to_keep,
        input_duration_sec=duration_sec,
        resulting_length_sec=resulting_length,
        resolved_noise_threshold=chosen_db,
        resolved_min_duration=chosen_min_dur,
        resolved_pad_sec=pad_sec,
        target_length=target_length,
    )
