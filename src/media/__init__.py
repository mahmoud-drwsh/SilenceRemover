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
from src.media.trim import create_silence_removed_audio, trim_single_video

__all__ = [
    "TRIM_TIMESTAMP_EPSILON_SEC",
    "choose_threshold_and_padding_for_target",
    "calculate_resulting_length",
    "detect_silence_points",
    "detect_silences_simple",
    "find_optimal_padding",
    "normalize_timestamp",
    "truncate_segments_to_max_length",
    "create_silence_removed_audio",
    "trim_single_video",
]
