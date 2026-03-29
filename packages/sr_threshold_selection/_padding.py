"""Padding optimization algorithm.

Moved from src.media.silence_detector for cohesion with threshold selection.
"""

from src.core.constants import (
    MAX_PAD_SEC,
    PAD_INCREMENT_SEC,
    TRIM_DECIMAL_PLACES,
    TRIM_TIMESTAMP_EPSILON_SEC,
)


def _normalize_timestamp(value: float, *, minimum: float = 0.0) -> float:
    """Normalize a timestamp to the configured trimming precision."""
    normalized = round(float(value), TRIM_DECIMAL_PLACES)
    if normalized < minimum:
        normalized = minimum
    if normalized == -0.0:
        normalized = 0.0
    return normalized


def _build_keep_segments(
    silence_starts: list[float],
    silence_ends: list[float],
    duration_sec: float,
    pad_sec: float,
) -> list[tuple[float, float]]:
    """Build keep-segments from silence intervals with shared padding logic."""
    pad_sec = _normalize_timestamp(max(0.0, pad_sec))
    duration_sec = _normalize_timestamp(duration_sec)
    
    # Normalize pair lists
    starts = [_normalize_timestamp(x, minimum=0.0) for x in silence_starts]
    ends = [_normalize_timestamp(x, minimum=0.0) for x in silence_ends]
    if len(starts) > len(ends):
        ends = list(ends) + [duration_sec]
    elif len(starts) < len(ends):
        ends = list(ends[: len(starts)])
    
    segments_to_keep: list[tuple[float, float]] = []
    prev_end = 0.0
    
    for silence_start, silence_end in zip(starts, ends):
        if silence_end - silence_start <= pad_sec * 2 + TRIM_TIMESTAMP_EPSILON_SEC:
            continue
        if silence_start > prev_end + TRIM_TIMESTAMP_EPSILON_SEC:
            segments_to_keep.append((_normalize_timestamp(prev_end), _normalize_timestamp(silence_start)))
        prev_end = _normalize_timestamp(max(0.0, silence_end - pad_sec))
    
    if prev_end < duration_sec - TRIM_TIMESTAMP_EPSILON_SEC:
        segments_to_keep.append((_normalize_timestamp(prev_end), _normalize_timestamp(duration_sec)))
    
    return segments_to_keep


def _calculate_resulting_length(
    silence_starts: list[float],
    silence_ends: list[float],
    duration_sec: float,
    pad_sec: float,
) -> float:
    """Calculate the resulting video length after trimming silences with padding."""
    segments_to_keep = _build_keep_segments(silence_starts, silence_ends, duration_sec, pad_sec)
    return _normalize_timestamp(sum(end - start for start, end in segments_to_keep))


def find_optimal_padding(
    silence_starts: list[float],
    silence_ends: list[float],
    duration_sec: float,
    target_length: float,
) -> float:
    """Find the optimal padding value to achieve a target video length.
    
    Iteratively increases padding from 0 to MAX_PAD_SEC in PAD_INCREMENT_SEC
    steps until the resulting length meets or exceeds the target.
    
    Args:
        silence_starts: List of silence start times in seconds
        silence_ends: List of silence end times in seconds
        duration_sec: Total video duration in seconds
        target_length: Desired resulting video length in seconds
        
    Returns:
        Optimal padding value in seconds (0 if target already met or exceeded)
    """
    if target_length >= duration_sec - TRIM_TIMESTAMP_EPSILON_SEC:
        return 0.0
    if not silence_starts:
        return 0.0
    
    result_with_0 = _calculate_resulting_length(silence_starts, silence_ends, duration_sec, 0.0)
    if result_with_0 + TRIM_TIMESTAMP_EPSILON_SEC > target_length:
        return 0.0
    
    max_pad = MAX_PAD_SEC
    pad_increment = PAD_INCREMENT_SEC
    if pad_increment <= 0:
        return 0.0
    
    max_steps = int(max_pad / pad_increment + TRIM_TIMESTAMP_EPSILON_SEC)
    best_pad = 0.0
    
    for step in range(max_steps + 1):
        current_pad = _normalize_timestamp(min(max_pad, step * pad_increment))
        resulting_length = _calculate_resulting_length(silence_starts, silence_ends, duration_sec, current_pad)
        if resulting_length < target_length - TRIM_TIMESTAMP_EPSILON_SEC:
            best_pad = current_pad
            continue
        break
    
    return best_pad
