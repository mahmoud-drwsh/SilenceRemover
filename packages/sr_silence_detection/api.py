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

from sr_silence_detection._cache import (
    get_cached_edge_detection,
    get_cached_primary_detection,
    save_edge_detection,
    save_primary_detection,
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


def detect_edge_only_cached(
    input_file: Path,
    temp_dir: Path | None,
    basename: str,
    edge_noise_threshold: float = -40.0,  # EDGE_RESCAN_THRESHOLD_DB
    edge_min_duration: float = 0.01,      # EDGE_RESCAN_MIN_DURATION_SEC
    edge_keep_seconds: float = 0.2,      # EDGE_SILENCE_KEEP_SEC
    duration_sec: float | None = None,
) -> tuple[list[float], list[float]]:
    """Detect edge silences with file-based caching.

    Args:
        input_file: Path to media file
        temp_dir: Directory for cache storage (if None, caching is skipped)
        basename: Base name for cache file identification
        edge_noise_threshold: Edge re-scan threshold in dB (more sensitive)
        edge_min_duration: Edge re-scan minimum duration in seconds
        edge_keep_seconds: Seconds to preserve at media start/end
        duration_sec: Optional media duration in seconds. If None, duration
            will be probed from the input file.

    Returns:
        Tuple of (edge_starts, edge_ends) as lists of timestamps.
    """
    # 1. Try cache first via _cache.get_cached_edge_detection() (if temp_dir provided)
    if temp_dir is not None:
        cached = get_cached_edge_detection(
            temp_dir,
            basename,
            input_file,
            edge_noise_threshold,
            edge_min_duration,
            edge_keep_seconds,
        )
        if cached is not None:
            # 2. If cache hit, extract and return (edge_starts, edge_ends)
            edge_starts, edge_ends, _duration_sec = cached
            return (edge_starts, edge_ends)

    # 3. If cache miss or no temp_dir (caching disabled):
    #    - Run _detect_raw(input_file, edge_noise_threshold, edge_min_duration)
    edge_starts, edge_ends = _detect_raw(input_file, edge_noise_threshold, edge_min_duration)

    #    - Get duration via _probe_duration_safe(input_file) only if not provided
    if duration_sec is None:
        duration_sec = normalize_timestamp(_probe_duration_safe(input_file))

    #    - Apply trim_edge_silence() with edge_keep_seconds
    edge_starts, edge_ends = trim_edge_silence(
        edge_starts,
        edge_ends,
        duration_sec,
        keep_seconds=edge_keep_seconds,
    )

    #    - Save to cache via _cache.save_edge_detection() (only if temp_dir provided)
    if temp_dir is not None:
        save_edge_detection(
            temp_dir,
            basename,
            input_file,
            edge_starts,
            edge_ends,
            duration_sec,
            edge_noise_threshold,
            edge_min_duration,
            edge_keep_seconds,
        )

    # 4. Return (edge_starts, edge_ends)
    return (edge_starts, edge_ends)


def detect_primary_with_cached_edges(
    input_file: Path,
    primary_noise_threshold: float,
    primary_min_duration: float,
    edge_starts: list[float],
    edge_ends: list[float],
    edge_keep_seconds: float = 0.2,  # EDGE_SILENCE_KEEP_SEC
    duration_sec: float | None = None,
    temp_dir: Path | None = None,
    basename: str | None = None,
) -> tuple[list[float], list[float]]:
    """Primary detection combining with pre-computed edge intervals.

    Supports file-based caching when temp_dir and basename are provided.
    This eliminates redundant FFmpeg calls on re-runs with the same threshold.

    Args:
        input_file: Path to media file
        primary_noise_threshold: Main detection threshold in dB
        primary_min_duration: Main detection minimum duration in seconds
        edge_starts: Pre-computed edge silence start timestamps
        edge_ends: Pre-computed edge silence end timestamps
        edge_keep_seconds: Seconds to preserve at media start/end
        duration_sec: Optional media duration in seconds. If None, duration
            will be probed from the input file.
        temp_dir: Optional directory for cache storage (enables caching if provided)
        basename: Optional base name for cache file identification

    Returns:
        Tuple of (silence_starts, silence_ends) as lists of timestamps.
        Primary edge intervals are replaced with cached edge intervals.
    """
    # 0. Check cache first if caching is enabled
    if temp_dir is not None and basename is not None:
        cached = get_cached_primary_detection(
            temp_dir,
            basename,
            input_file,
            primary_noise_threshold,
            primary_min_duration,
        )
        if cached is not None:
            # Cache hit: use cached silence intervals
            silence_starts, silence_ends, duration_sec_cached = cached
            
            # Use cached duration if not explicitly provided
            if duration_sec is None:
                duration_sec = duration_sec_cached
            
            # Still need to apply edge replacement and trimming with current edge params
            leading_edge, trailing_edge = _leading_trailing_from_edge_lists(
                edge_starts,
                edge_ends,
                duration_sec,
                keep_seconds=edge_keep_seconds,
            )
            
            silence_starts, silence_ends = replace_edge_intervals(
                silence_starts,
                silence_ends,
                leading_edge,
                trailing_edge,
                duration_sec,
            )
            
            return trim_edge_silence(
                silence_starts,
                silence_ends,
                duration_sec,
                keep_seconds=edge_keep_seconds,
            )

    # 1. Get duration via _probe_duration_safe(input_file) only if not provided
    if duration_sec is None:
        duration_sec = normalize_timestamp(_probe_duration_safe(input_file))

    # 2. Run _detect_raw(input_file, primary_noise_threshold, primary_min_duration)
    silence_starts, silence_ends = _detect_raw(input_file, primary_noise_threshold, primary_min_duration)

    # 3. Derive leading/trailing from cached edge intervals using _leading_trailing_from_edge_lists()
    leading_edge, trailing_edge = _leading_trailing_from_edge_lists(
        edge_starts,
        edge_ends,
        duration_sec,
        keep_seconds=edge_keep_seconds,
    )

    # 4. Replace primary edge intervals with cached edge intervals using replace_edge_intervals()
    silence_starts, silence_ends = replace_edge_intervals(
        silence_starts,
        silence_ends,
        leading_edge,
        trailing_edge,
        duration_sec,
    )

    # 5. Apply trim_edge_silence() with edge_keep_seconds
    result = trim_edge_silence(
        silence_starts,
        silence_ends,
        duration_sec,
        keep_seconds=edge_keep_seconds,
    )

    # 6. Save to cache if caching is enabled
    if temp_dir is not None and basename is not None:
        save_primary_detection(
            temp_dir,
            basename,
            input_file,
            silence_starts,
            silence_ends,
            duration_sec,
            primary_noise_threshold,
            primary_min_duration,
        )

    # 7. Return result
    return result
