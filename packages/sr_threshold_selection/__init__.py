"""Threshold selection black box for trim planning.

Pure algorithm package for selecting optimal noise threshold and padding
to achieve target video length.
"""

from sr_threshold_selection.api import (
    ThresholdCandidate,
    SelectionResult,
    select_threshold_and_padding,
    build_candidates_from_detection_results,
)
from sr_threshold_selection._padding import find_optimal_padding

__all__ = [
    "ThresholdCandidate",
    "SelectionResult",
    "select_threshold_and_padding",
    "build_candidates_from_detection_results",
    "find_optimal_padding",
]
