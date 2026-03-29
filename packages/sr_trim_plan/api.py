"""Trim planning policy shared by snippet and final render flows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from src.core.constants import (
    EDGE_RESCAN_MIN_DURATION_SEC,
    EDGE_RESCAN_THRESHOLD_DB,
    EDGE_SILENCE_KEEP_SEC,
    TARGET_NOISE_THRESHOLDS_DB,
    TRIM_TIMESTAMP_EPSILON_SEC,
    TrimDefaults,
    resolve_trim_defaults,
)
from src.ffmpeg.probing import probe_duration
from src.media.silence_detector import (
    build_keep_segments_from_silences,
    normalize_timestamp,
    truncate_segments_to_max_length,
)
from sr_silence_detection import detect_silence_with_edges
from sr_threshold_selection import (
    ThresholdCandidate,
    SelectionResult,
    select_threshold_and_padding,
)

TrimPlanMode = Literal["target", "non_target"]


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


def _collect_threshold_candidates(
    input_file: Path,
    duration_sec: float,
    min_duration: float,
    noise_thresholds_db: list[float],
    override_noise_threshold: float | None,
) -> list[ThresholdCandidate]:
    """Detect silence for all thresholds and build candidate list.
    
    Args:
        input_file: Path to media file
        duration_sec: Media duration in seconds
        min_duration: Minimum silence duration for detection
        noise_thresholds_db: List of thresholds to try (ordered quiet -> aggressive)
        override_noise_threshold: Optional threshold to prepend to the list
        
    Returns:
        List of ThresholdCandidate objects for all tested thresholds
    """
    from src.media.silence_detector import calculate_resulting_length
    
    ordered_thresholds = list(noise_thresholds_db)
    if override_noise_threshold is not None and override_noise_threshold not in ordered_thresholds:
        ordered_thresholds = [override_noise_threshold] + ordered_thresholds
    
    candidates = []
    for threshold_db in ordered_thresholds:
        silence_starts, silence_ends = detect_silence_with_edges(
            input_file=input_file,
            primary_noise_threshold=threshold_db,
            primary_min_duration=min_duration,
            edge_noise_threshold=EDGE_RESCAN_THRESHOLD_DB,
            edge_min_duration=EDGE_RESCAN_MIN_DURATION_SEC,
            edge_keep_seconds=EDGE_SILENCE_KEEP_SEC,
        )
        base_length = calculate_resulting_length(silence_starts, silence_ends, duration_sec, 0.0)
        candidates.append(ThresholdCandidate(
            threshold_db=threshold_db,
            silence_starts=silence_starts,
            silence_ends=silence_ends,
            base_trimmed_length_sec=base_length,
            duration_sec=duration_sec,
        ))
    
    return candidates


def _build_target_trim_plan(
    input_file: Path,
    duration_sec: float,
    target_length: float,
    trim_defaults: TrimDefaults,
) -> TrimPlan:
    """Build a target-mode trim plan with adaptive threshold/padding policy."""
    # Step 1: Collect candidates for all thresholds
    candidates = _collect_threshold_candidates(
        input_file=input_file,
        duration_sec=duration_sec,
        min_duration=trim_defaults.min_duration,
        noise_thresholds_db=TARGET_NOISE_THRESHOLDS_DB,
        override_noise_threshold=trim_defaults.noise_threshold,
    )
    
    # Step 2: Use black box to select optimal threshold and padding
    selection = select_threshold_and_padding(
        candidates=candidates,
        target_length_sec=target_length,
    )
    
    # Step 3: Build segments with chosen padding
    segments_to_keep = build_keep_segments_from_silences(
        silence_starts=selection.chosen_starts,
        silence_ends=selection.chosen_ends,
        duration_sec=duration_sec,
        pad_sec=selection.pad_sec,
    )
    resulting_length = normalize_timestamp(sum(end - start for start, end in segments_to_keep))

    # Step 4: Final safeguard - truncate if still over target
    if resulting_length > target_length + TRIM_TIMESTAMP_EPSILON_SEC:
        segments_to_keep = truncate_segments_to_max_length(segments_to_keep, target_length)
        resulting_length = normalize_timestamp(sum(end - start for start, end in segments_to_keep))

    print(
        f"Target mode: chosen noise_threshold={selection.chosen_threshold_db}dB, "
        f"min_duration={trim_defaults.min_duration}s, pad={selection.pad_sec}s, "
        f"fallback={selection.fallback_to_most_aggressive}"
    )
    return TrimPlan(
        mode="target",
        segments_to_keep=segments_to_keep,
        input_duration_sec=duration_sec,
        resulting_length_sec=resulting_length,
        resolved_noise_threshold=selection.chosen_threshold_db,
        resolved_min_duration=trim_defaults.min_duration,
        resolved_pad_sec=selection.pad_sec,
        target_length=target_length,
    )
from src.ffmpeg.probing import probe_duration
from src.media.silence_detector import (
    build_keep_segments_from_silences,
    calculate_resulting_length,
    find_optimal_padding,
    normalize_timestamp,
    truncate_segments_to_max_length,
)
from sr_silence_detection import detect_silence_with_edges

TrimPlanMode = Literal["target", "non_target"]


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


def _choose_threshold_and_padding_for_target(
    input_file: Path,
    duration_sec: float,
    target_length: float,
    *,
    min_duration: float,
    noise_thresholds_db: list[float],
    override_noise_threshold: float | None = None,
) -> tuple[list[float], list[float], float, float]:
    """Pick the least-aggressive threshold that can meet target, then tune padding.

    Sweep thresholds from quiet -> more aggressive until the base trimmed length
    (pad=0) is <= target. Then maximize uniform padding without ever exceeding
    the target.

    Returns:
        (silence_starts, silence_ends, chosen_threshold_db, pad_sec)
    """
    if noise_thresholds_db is None:
        from src.core.constants import TARGET_NOISE_THRESHOLD_DB

        noise_thresholds_db = [TARGET_NOISE_THRESHOLD_DB]

    ordered_thresholds = list(noise_thresholds_db)
    if override_noise_threshold is not None and override_noise_threshold not in ordered_thresholds:
        ordered_thresholds = [override_noise_threshold] + ordered_thresholds

    chosen_threshold = ordered_thresholds[0]
    chosen_pad = 0.0
    chosen_starts: list[float] = []
    chosen_ends: list[float] = []
    last_starts: list[float] = []
    last_ends: list[float] = []

    for threshold_db in ordered_thresholds:
        silence_starts, silence_ends = detect_silence_with_edges(
            input_file=input_file,
            primary_noise_threshold=threshold_db,
            primary_min_duration=min_duration,
            edge_noise_threshold=EDGE_RESCAN_THRESHOLD_DB,
            edge_min_duration=EDGE_RESCAN_MIN_DURATION_SEC,
            edge_keep_seconds=EDGE_SILENCE_KEEP_SEC,
        )
        last_starts, last_ends = silence_starts, silence_ends

        base_length = calculate_resulting_length(silence_starts, silence_ends, duration_sec, 0.0)
        if base_length > target_length:
            continue

        chosen_threshold = threshold_db
        chosen_starts = silence_starts
        chosen_ends = silence_ends
        chosen_pad = find_optimal_padding(silence_starts, silence_ends, duration_sec, target_length)
        break
    else:
        # If nothing can meet target with silence trimming alone, use the most aggressive
        # threshold we tried and pad=0; caller can apply truncation as a final safeguard.
        if ordered_thresholds:
            chosen_threshold = ordered_thresholds[-1]
        chosen_starts, chosen_ends = last_starts, last_ends
        chosen_pad = 0.0

    return (chosen_starts, chosen_ends, chosen_threshold, chosen_pad)


def _build_target_trim_plan(
    input_file: Path,
    duration_sec: float,
    target_length: float,
    trim_defaults: TrimDefaults,
) -> TrimPlan:
    """Build a target-mode trim plan with adaptive threshold/padding policy."""
    silence_starts, silence_ends, chosen_threshold, chosen_pad = _choose_threshold_and_padding_for_target(
        input_file=input_file,
        duration_sec=duration_sec,
        target_length=target_length,
        min_duration=trim_defaults.min_duration,
        noise_thresholds_db=TARGET_NOISE_THRESHOLDS_DB,
        override_noise_threshold=trim_defaults.noise_threshold,
    )
    segments_to_keep = build_keep_segments_from_silences(
        silence_starts=silence_starts,
        silence_ends=silence_ends,
        duration_sec=duration_sec,
        pad_sec=chosen_pad,
    )
    resulting_length = normalize_timestamp(sum(end - start for start, end in segments_to_keep))

    if resulting_length > target_length + TRIM_TIMESTAMP_EPSILON_SEC:
        segments_to_keep = truncate_segments_to_max_length(segments_to_keep, target_length)
        resulting_length = normalize_timestamp(sum(end - start for start, end in segments_to_keep))

    print(
        f"Target mode: chosen noise_threshold={chosen_threshold}dB, "
        f"min_duration={trim_defaults.min_duration}s, pad={chosen_pad}s"
    )
    return TrimPlan(
        mode="target",
        segments_to_keep=segments_to_keep,
        input_duration_sec=duration_sec,
        resulting_length_sec=resulting_length,
        resolved_noise_threshold=chosen_threshold,
        resolved_min_duration=trim_defaults.min_duration,
        resolved_pad_sec=chosen_pad,
        target_length=target_length,
    )
