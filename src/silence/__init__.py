"""Silence package: detection utilities shared across trimming."""

from .detector import (
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

