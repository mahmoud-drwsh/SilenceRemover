"""Silence detection and trimming algorithm utilities."""

from pathlib import Path

from src.core.constants import (
    MAX_PAD_SEC,
    PAD_INCREMENT_SEC,
    TRIM_DECIMAL_PLACES,
    TRIM_TIMESTAMP_EPSILON_SEC,
    SIMPLE_DB,
    SIMPLE_MIN_DURATION,
    TARGET_MIN_DURATION,
    TARGET_NOISE_THRESHOLDS_DB,
)
from src.ffmpeg.detection import detect_silence_points as detect_silence_points_via_ffmpeg


def normalize_timestamp(value: float, *, minimum: float = 0.0) -> float:
    """Normalize a timestamp to the configured trimming precision."""
    normalized = round(float(value), TRIM_DECIMAL_PLACES)
    if normalized < minimum:
        normalized = minimum
    if normalized == -0.0:
        normalized = 0.0
    return normalized


def calculate_resulting_length(silence_starts: list[float], silence_ends: list[float], duration_sec: float, pad_sec: float) -> float:
    """Calculate the resulting video length after trimming silences with padding.
    
    Args:
        silence_starts: List of silence start times in seconds
        silence_ends: List of silence end times in seconds
        duration_sec: Total video duration in seconds
        pad_sec: Padding to retain around silences in seconds
        
    Returns:
        Total length of segments to keep in seconds
    """
    pad_sec = normalize_timestamp(max(0.0, pad_sec))
    duration_sec = normalize_timestamp(duration_sec)
    silence_starts = [normalize_timestamp(x) for x in silence_starts]
    silence_ends = [normalize_timestamp(x) for x in silence_ends]

    if len(silence_starts) != len(silence_ends):
        if len(silence_starts) > len(silence_ends):
            silence_ends = list(silence_ends) + [duration_sec]
        else:
            silence_ends = list(silence_ends)
    segments_to_keep: list[tuple[float, float]] = []
    prev_end = 0.0
    for silence_start, silence_end in zip(silence_starts, silence_ends):
        if silence_end - silence_start <= pad_sec * 2 + TRIM_TIMESTAMP_EPSILON_SEC:
            continue
        if silence_start > prev_end + TRIM_TIMESTAMP_EPSILON_SEC:
            segments_to_keep.append((normalize_timestamp(prev_end), normalize_timestamp(silence_start)))
        prev_end = normalize_timestamp(max(0.0, silence_end - pad_sec))
    if prev_end < duration_sec - TRIM_TIMESTAMP_EPSILON_SEC:
        segments_to_keep.append((normalize_timestamp(prev_end), normalize_timestamp(duration_sec)))
    return normalize_timestamp(sum(end - start for start, end in segments_to_keep))


def find_optimal_padding(silence_starts: list[float], silence_ends: list[float], duration_sec: float, target_length: float) -> float:
    """Find the optimal padding value to achieve a target video length.
    
    Args:
        silence_starts: List of silence start times in seconds
        silence_ends: List of silence end times in seconds
        duration_sec: Total video duration in seconds
        target_length: Desired resulting video length in seconds
        
    Returns:
        Optimal padding value in seconds
    """
    if target_length >= duration_sec - TRIM_TIMESTAMP_EPSILON_SEC:
        return 0.0
    if not silence_starts:
        return 0.0
    result_with_0 = calculate_resulting_length(silence_starts, silence_ends, duration_sec, 0.0)
    if result_with_0 + TRIM_TIMESTAMP_EPSILON_SEC > target_length:
        return 0.0
    max_pad = MAX_PAD_SEC
    pad_increment = PAD_INCREMENT_SEC
    if pad_increment <= 0:
        return 0.0
    max_steps = int(max_pad / pad_increment + TRIM_TIMESTAMP_EPSILON_SEC)
    best_pad = 0.0
    for step in range(max_steps + 1):
        current_pad = normalize_timestamp(min(max_pad, step * pad_increment))
        resulting_length = calculate_resulting_length(silence_starts, silence_ends, duration_sec, current_pad)
        if resulting_length < target_length - TRIM_TIMESTAMP_EPSILON_SEC:
            best_pad = current_pad
            continue
        break
    return best_pad


def truncate_segments_to_max_length(
    segments_to_keep: list[tuple[float, float]],
    max_length_sec: float,
) -> list[tuple[float, float]]:
    """Truncate segments from the end so total length <= max_length_sec.

    This is a last-resort safeguard to guarantee we never exceed the target,
    even if silence detection cannot reduce the output enough (e.g. almost no
    detected silences or an extremely small target).
    """
    if max_length_sec <= 0:
        return []

    out: list[tuple[float, float]] = []
    remaining = max_length_sec
    for start, end in segments_to_keep:
        seg_len = max(0.0, end - start)
        if seg_len <= 0:
            continue
        if seg_len <= remaining:
            out.append((start, end))
            remaining -= seg_len
            if remaining <= 0:
                break
        else:
            out.append((start, normalize_timestamp(start + remaining)))
            remaining = 0.0
            break
    return out


def choose_threshold_and_padding_for_target(
    input_file: Path,
    duration_sec: float,
    target_length: float,
    *,
    min_duration: float = TARGET_MIN_DURATION,
    noise_thresholds_db: list[float] = TARGET_NOISE_THRESHOLDS_DB,
) -> tuple[list[float], list[float], float, float]:
    """Pick the least-aggressive threshold that can meet target, then tune padding.

    Sweep thresholds from quiet -> more aggressive until the base trimmed length
    (pad=0) is <= target. Then maximize uniform padding without ever exceeding
    the target.

    Returns:
        (silence_starts, silence_ends, chosen_threshold_db, pad_sec)
    """
    if target_length >= duration_sec:
        return ([], [], noise_thresholds_db[0] if noise_thresholds_db else -60.0, 0.0)

    chosen_threshold = noise_thresholds_db[0] if noise_thresholds_db else -60.0
    chosen_pad = 0.0
    chosen_starts: list[float] = []
    chosen_ends: list[float] = []

    for threshold_db in (noise_thresholds_db or [-60.0]):
        silence_starts, silence_ends = detect_silence_points(input_file, threshold_db, min_duration)
        if len(silence_starts) > len(silence_ends):
            silence_ends = list(silence_ends) + [duration_sec]

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
        if noise_thresholds_db:
            chosen_threshold = noise_thresholds_db[-1]
        chosen_starts, chosen_ends = detect_silence_points(input_file, chosen_threshold, min_duration)
        if len(chosen_starts) > len(chosen_ends):
            chosen_ends = list(chosen_ends) + [duration_sec]
        chosen_pad = 0.0

    return (chosen_starts, chosen_ends, chosen_threshold, chosen_pad)


def detect_silence_points(input_file: Path, noise_threshold: float, min_duration: float) -> tuple[list[float], list[float]]:
    return detect_silence_points_via_ffmpeg(input_file, noise_threshold, min_duration)


def detect_silences_simple(input_file: Path) -> tuple[list[float], list[float]]:
    """Detect all silences with fixed settings when --target-length is set.

    Uses SIMPLE_DB and SIMPLE_MIN_DURATION for a single detection pass.
    """
    return detect_silence_points(input_file, SIMPLE_DB, SIMPLE_MIN_DURATION)


__all__ = [
    "calculate_resulting_length",
    "normalize_timestamp",
    "find_optimal_padding",
    "choose_threshold_and_padding_for_target",
    "truncate_segments_to_max_length",
    "detect_silence_points",
    "detect_silences_simple",
]

