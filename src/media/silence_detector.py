"""Silence detection and trimming algorithm utilities."""

from pathlib import Path

from src.core.constants import (
    MAX_PAD_SEC,
    PAD_INCREMENT_SEC,
    EDGE_SILENCE_KEEP_SEC,
    TRIM_DECIMAL_PLACES,
    TRIM_TIMESTAMP_EPSILON_SEC,
    TARGET_NOISE_THRESHOLD_DB,
    TARGET_MIN_DURATION_SEC,
    SNIPPET_MIN_DURATION_SEC,
    TARGET_NOISE_THRESHOLDS_DB,
)
from src.ffmpeg.detection import detect_silence_points as detect_silence_points_via_ffmpeg

EDGE_RESCAN_THRESHOLD_DB = -55.0


def normalize_timestamp(value: float, *, minimum: float = 0.0) -> float:
    """Normalize a timestamp to the configured trimming precision."""
    normalized = round(float(value), TRIM_DECIMAL_PLACES)
    if normalized < minimum:
        normalized = minimum
    if normalized == -0.0:
        normalized = 0.0
    return normalized


def _normalize_pair_lists(silence_starts: list[float], silence_ends: list[float], duration_sec: float) -> tuple[list[float], list[float]]:
    starts = [normalize_timestamp(x, minimum=0.0) for x in silence_starts]
    ends = [normalize_timestamp(x, minimum=0.0) for x in silence_ends]
    if len(starts) > len(ends):
        ends = list(ends) + [duration_sec]
    elif len(starts) < len(ends):
        ends = list(ends[: len(starts)])
    return starts, ends


def detect_leading_trailing_edge_silence(
    input_file: Path,
    duration_sec: float,
    *,
    keep_seconds: float = EDGE_SILENCE_KEEP_SEC,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    """Detect only leading/trailing silence using a conservative edge re-scan."""
    edge_starts, edge_ends = detect_silence_points(
        input_file,
        EDGE_RESCAN_THRESHOLD_DB,
        SNIPPET_MIN_DURATION_SEC,
    )
    edge_starts, edge_ends = trim_edge_silence(edge_starts, edge_ends, duration_sec, keep_seconds=keep_seconds)
    if not edge_starts or not edge_ends:
        return None, None

    leading = None
    trailing = None

    if edge_starts[0] <= TRIM_TIMESTAMP_EPSILON_SEC:
        leading = (edge_starts[0], edge_ends[0])

    if edge_ends[-1] >= duration_sec - TRIM_TIMESTAMP_EPSILON_SEC:
        trailing = (edge_starts[-1], edge_ends[-1])

    return leading, trailing


def replace_edge_intervals(
    silence_starts: list[float],
    silence_ends: list[float],
    leading_edge: tuple[float, float] | None,
    trailing_edge: tuple[float, float] | None,
    duration_sec: float,
) -> tuple[list[float], list[float]]:
    """Replace only leading and trailing intervals in `silence_starts/ends`."""
    starts, ends = _normalize_pair_lists(silence_starts, silence_ends, duration_sec)

    if not starts or not ends:
        return [], []

    if starts[0] <= TRIM_TIMESTAMP_EPSILON_SEC and leading_edge is not None:
        starts[0], ends[0] = leading_edge

    if ends[-1] >= duration_sec - TRIM_TIMESTAMP_EPSILON_SEC and trailing_edge is not None:
        starts[-1], ends[-1] = trailing_edge

    return starts, ends


def trim_edge_silence(
    silence_starts: list[float],
    silence_ends: list[float],
    duration_sec: float,
    *,
    keep_seconds: float = EDGE_SILENCE_KEEP_SEC,
) -> tuple[list[float], list[float]]:
    """Reserve `keep_seconds` at each edge and remove edge silence beyond that.

    When a leading silence starts at the beginning, keep only the last
    `keep_seconds` of that leading silence. Same for a trailing silence ending
    at the end of media.
    """
    keep_seconds = max(0.0, keep_seconds)
    starts, ends = _normalize_pair_lists(silence_starts, silence_ends, duration_sec)
    if not starts or not ends:
        return [], []

    # Leading silence: trim all but keep_seconds near time 0.
    if starts[0] <= TRIM_TIMESTAMP_EPSILON_SEC:
        trimmed_end = ends[0] - keep_seconds
        if trimmed_end > TRIM_TIMESTAMP_EPSILON_SEC:
            starts[0] = 0.0
            ends[0] = normalize_timestamp(trimmed_end)
        else:
            starts.pop(0)
            ends.pop(0)

    if not starts or not ends:
        return [], []

    # Trailing silence: trim all but keep_seconds near final timestamp.
    if ends[-1] >= duration_sec - TRIM_TIMESTAMP_EPSILON_SEC:
        trimmed_start = max(0.0, duration_sec - keep_seconds)
        if trimmed_start - starts[-1] > TRIM_TIMESTAMP_EPSILON_SEC:
            starts[-1] = normalize_timestamp(trimmed_start)
        else:
            starts.pop(-1)
            ends.pop(-1)

    return starts, ends


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
    min_duration: float = TARGET_MIN_DURATION_SEC,
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

    leading_edge, trailing_edge = detect_leading_trailing_edge_silence(input_file, duration_sec)

    for threshold_db in (noise_thresholds_db or [-60.0]):
        silence_starts, silence_ends = detect_silence_points(input_file, threshold_db, min_duration)
        silence_starts, silence_ends = replace_edge_intervals(
            silence_starts,
            silence_ends,
            leading_edge,
            trailing_edge,
            duration_sec,
        )
        silence_starts, silence_ends = trim_edge_silence(silence_starts, silence_ends, duration_sec)

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
        chosen_starts, chosen_ends = replace_edge_intervals(
            chosen_starts,
            chosen_ends,
            leading_edge,
            trailing_edge,
            duration_sec,
        )
        chosen_starts, chosen_ends = trim_edge_silence(chosen_starts, chosen_ends, duration_sec)
        chosen_pad = 0.0

    return (chosen_starts, chosen_ends, chosen_threshold, chosen_pad)


def detect_silence_points(input_file: Path, noise_threshold: float, min_duration: float) -> tuple[list[float], list[float]]:
    return detect_silence_points_via_ffmpeg(input_file, noise_threshold, min_duration)


def detect_silences_simple(input_file: Path) -> tuple[list[float], list[float]]:
    """Detect all silences with fixed settings when --target-length is set.

    Uses TARGET_NOISE_THRESHOLD_DB and TARGET_MIN_DURATION_SEC for a single detection pass.
    """
    return detect_silence_points(input_file, TARGET_NOISE_THRESHOLD_DB, TARGET_MIN_DURATION_SEC)


__all__ = [
    "calculate_resulting_length",
    "normalize_timestamp",
    "find_optimal_padding",
    "choose_threshold_and_padding_for_target",
    "trim_edge_silence",
    "truncate_segments_to_max_length",
    "detect_silence_points",
    "detect_silences_simple",
]

