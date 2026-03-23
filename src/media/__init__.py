"""Media domain package for silence detection and trimming."""

from src.media.silence_detector import (
    TRIM_TIMESTAMP_EPSILON_SEC,
    choose_threshold_and_padding_for_target,
    calculate_resulting_length,
    detect_silence_points,
    detect_silences_simple,
    find_optimal_padding,
    normalize_timestamp,
    truncate_segments_to_max_length,
)
def trim_single_video(*args, **kwargs):
    from src.media.trim import trim_single_video as _trim_single_video

    return _trim_single_video(*args, **kwargs)

__all__ = [
    "TRIM_TIMESTAMP_EPSILON_SEC",
    "choose_threshold_and_padding_for_target",
    "calculate_resulting_length",
    "detect_silence_points",
    "detect_silences_simple",
    "find_optimal_padding",
    "normalize_timestamp",
    "truncate_segments_to_max_length",
    "trim_single_video",
]
