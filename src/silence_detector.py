"""Backward-compatibility shim for silence detection utilities.

The actual implementations now live in `src.silence.detector`, but this module
keeps the old import paths working (e.g. `from src.silence_detector import ...`).
"""

from src.silence.detector import (
    calculate_resulting_length,
    find_optimal_padding,
    detect_silence_points,
    detect_silences_simple,
)

__all__ = [
    "calculate_resulting_length",
    "find_optimal_padding",
    "detect_silence_points",
    "detect_silences_simple",
]
