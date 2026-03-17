"""Backward-compatibility shim for silence detection utilities.

The actual implementations now live in `src.silence.detector`, but this module
keeps the old import paths working (e.g. `from src.silence_detector import ...`).
"""

from src.silence.detector import (
    calculate_resulting_length,
    choose_threshold_and_padding_for_target,
    find_optimal_padding,
    detect_silence_points,
    detect_silences_simple,
    normalize_timestamp,
    truncate_segments_to_max_length,
)

__all__ = [
    "calculate_resulting_length",
    "choose_threshold_and_padding_for_target",
    "find_optimal_padding",
    "normalize_timestamp",
    "detect_silence_points",
    "detect_silences_simple",
    "truncate_segments_to_max_length",
]
