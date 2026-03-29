"""Threshold selection API for trim planning.

Pure algorithm: no FFmpeg dependencies, operates on pre-computed detection results.
"""

from dataclasses import dataclass
from typing import Optional

from sr_threshold_selection._padding import find_optimal_padding
from src.core.constants import TRIM_TIMESTAMP_EPSILON_SEC


@dataclass(frozen=True)
class ThresholdCandidate:
    """Pre-computed silence detection result for a specific threshold."""
    
    threshold_db: float
    silence_starts: list[float]
    silence_ends: list[float]
    base_trimmed_length_sec: float  # Length with pad=0
    duration_sec: float  # Original media duration


@dataclass(frozen=True)
class SelectionResult:
    """Result of threshold and padding selection algorithm."""
    
    chosen_threshold_db: float
    chosen_starts: list[float]
    chosen_ends: list[float]
    pad_sec: float
    fallback_to_most_aggressive: bool  # True if no threshold met target


def select_threshold_and_padding(
    candidates: list[ThresholdCandidate],
    target_length_sec: float,
    *,
    epsilon_sec: float = TRIM_TIMESTAMP_EPSILON_SEC,
) -> SelectionResult:
    """Select least-aggressive threshold that meets target, with optimal padding.
    
    Algorithm:
    1. Sort candidates by threshold (quiet -> aggressive, e.g., -60dB to -45dB)
    2. Find first candidate where base_trimmed_length <= target
    3. Compute optimal padding for that candidate without exceeding target
    4. If no candidate meets target, fallback to most aggressive with pad=0
    
    Args:
        candidates: List of detection results for different thresholds
        target_length_sec: Desired resulting video length
        epsilon_sec: Tolerance for floating-point comparisons
        
    Returns:
        SelectionResult with chosen threshold, silence intervals, and padding
    """
    if not candidates:
        raise ValueError("No candidates provided for threshold selection")
    
    # Sort by threshold (more negative = quieter/less aggressive first)
    ordered = sorted(candidates, key=lambda c: c.threshold_db)
    
    last_candidate: Optional[ThresholdCandidate] = None
    
    for candidate in ordered:
        last_candidate = candidate
        
        # Check if base trimmed length (with pad=0) meets target
        if candidate.base_trimmed_length_sec > target_length_sec + epsilon_sec:
            # Too long even with no padding, try more aggressive threshold
            continue
        
        # Found threshold that can meet target - compute optimal padding
        pad_sec = find_optimal_padding(
            candidate.silence_starts,
            candidate.silence_ends,
            candidate.duration_sec,
            target_length_sec,
        )
        
        return SelectionResult(
            chosen_threshold_db=candidate.threshold_db,
            chosen_starts=candidate.silence_starts,
            chosen_ends=candidate.silence_ends,
            pad_sec=pad_sec,
            fallback_to_most_aggressive=False,
        )
    
    # No candidate met target - fallback to most aggressive threshold
    fallback = ordered[-1]
    
    return SelectionResult(
        chosen_threshold_db=fallback.threshold_db,
        chosen_starts=fallback.silence_starts,
        chosen_ends=fallback.silence_ends,
        pad_sec=0.0,
        fallback_to_most_aggressive=True,
    )


def build_candidates_from_detection_results(
    results: list[tuple[float, list[float], list[float], float]],
) -> list[ThresholdCandidate]:
    """Convert raw detection results to ThresholdCandidate objects.
    
    Args:
        results: List of (threshold_db, silence_starts, silence_ends, duration_sec)
        
    Returns:
        List of ThresholdCandidate objects with base_trimmed_length computed
    """
    from src.media.silence_detector import calculate_resulting_length
    
    candidates = []
    for threshold_db, starts, ends, duration_sec in results:
        base_length = calculate_resulting_length(starts, ends, duration_sec, 0.0)
        candidates.append(ThresholdCandidate(
            threshold_db=threshold_db,
            silence_starts=starts,
            silence_ends=ends,
            base_trimmed_length_sec=base_length,
            duration_sec=duration_sec,
        ))
    return candidates
