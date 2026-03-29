"""Public API: FFmpeg silence detection black box.

This module provides a clean interface for detecting silence intervals in media files.
All FFmpeg implementation details are encapsulated internally.

Input: Path + detection parameters
Output: (silence_starts, silence_ends) as lists of timestamps
"""

from __future__ import annotations

from pathlib import Path

from src.media.silence_detector import (
    _leading_trailing_from_edge_lists,
    normalize_timestamp,
    replace_edge_intervals,
    trim_edge_silence,
)

from sr_silence_detection._runner import _detect_dual_raw, _detect_raw, _probe_duration_safe


def detect_silence(
    input_file: Path,
    noise_threshold: float,
    min_duration: float,
) -> tuple[list[float], list[float]]:
    """Detect silence intervals using single FFmpeg pass.

    Args:
        input_file: Path to media file (video or audio)
        noise_threshold: Silence threshold in dB (e.g., -50.0)
        min_duration: Minimum silence duration in seconds

    Returns:
        Tuple of (silence_starts, silence_ends) as lists of timestamps in seconds.
        Returns empty lists if no audio stream detected.
    """
    return _detect_raw(input_file, noise_threshold, min_duration)


def detect_silence_with_edges(
    input_file: Path,
    primary_noise_threshold: float,
    primary_min_duration: float,
    edge_noise_threshold: float,
    edge_min_duration: float,
    edge_keep_seconds: float,
) -> tuple[list[float], list[float]]:
    """Detect silences with edge-aware policy.

    Uses dual-pass detection (primary + edge) and applies edge trimming
    to preserve buffer at start/end of media.

    The black box handles duration probing internally.

    Args:
        input_file: Path to media file
        primary_noise_threshold: Main detection threshold in dB
        primary_min_duration: Main detection minimum duration in seconds
        edge_noise_threshold: Edge re-scan threshold in dB (more sensitive)
        edge_min_duration: Edge re-scan minimum duration in seconds
        edge_keep_seconds: Seconds to preserve at media start/end

    Returns:
        Tuple of (silence_starts, silence_ends) as lists of timestamps.
        Silences are normalized with edge policy applied.
    """
    # Probe duration internally (as requested)
    duration_sec = normalize_timestamp(_probe_duration_safe(input_file))

    # Run dual detection: primary + edge
    (silence_starts, silence_ends), (edge_starts, edge_ends) = _detect_dual_raw(
        input_file,
        primary_noise_threshold,
        primary_min_duration,
        edge_noise_threshold,
        edge_min_duration,
    )

    # Derive leading/trailing edge intervals
    leading_edge, trailing_edge = _leading_trailing_from_edge_lists(
        edge_starts,
        edge_ends,
        duration_sec,
        keep_seconds=edge_keep_seconds,
    )

    # Replace primary edge intervals with edge-policy intervals
    silence_starts, silence_ends = replace_edge_intervals(
        silence_starts,
        silence_ends,
        leading_edge,
        trailing_edge,
        duration_sec,
    )

    # Apply final edge trimming
    return trim_edge_silence(
        silence_starts,
        silence_ends,
        duration_sec,
        keep_seconds=edge_keep_seconds,
    )
