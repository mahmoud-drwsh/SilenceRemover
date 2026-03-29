"""Silence detection and trimming algorithm utilities."""

from src.core.constants import (
    TRIM_DECIMAL_PLACES,
    TRIM_TIMESTAMP_EPSILON_SEC,
)

# Re-export find_optimal_padding from new black box for backward compatibility
from sr_threshold_selection import find_optimal_padding


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


def build_keep_segments_from_silences(
    silence_starts: list[float],
    silence_ends: list[float],
    duration_sec: float,
    pad_sec: float,
) -> list[tuple[float, float]]:
    """Build keep-segments from silence intervals with shared padding logic."""
    pad_sec = normalize_timestamp(max(0.0, pad_sec))
    duration_sec = normalize_timestamp(duration_sec)
    silence_starts, silence_ends = _normalize_pair_lists(silence_starts, silence_ends, duration_sec)
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
    return segments_to_keep


def _leading_trailing_from_edge_lists(
    edge_starts: list[float],
    edge_ends: list[float],
    duration_sec: float,
    *,
    keep_seconds: float,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    """Derive leading/trailing edge intervals from edge-policy silence lists."""
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
    keep_seconds: float,
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
    segments_to_keep = build_keep_segments_from_silences(
        silence_starts=silence_starts,
        silence_ends=silence_ends,
        duration_sec=duration_sec,
        pad_sec=pad_sec,
    )
    return normalize_timestamp(sum(end - start for start, end in segments_to_keep))


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


__all__ = [
    "calculate_resulting_length",
    "build_keep_segments_from_silences",
    "normalize_timestamp",
    "find_optimal_padding",
    "trim_edge_silence",
    "truncate_segments_to_max_length",
    "replace_edge_intervals",
    "_leading_trailing_from_edge_lists",
    "_normalize_pair_lists",
]

