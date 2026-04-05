"""Core utilities for FFmpeg filter graph building.

Pure functions for arithmetic and indexing operations.
"""


def _segment_audio_duration_sec(segment_start: float, segment_end: float) -> float:
    """Calculate segment duration with epsilon guard to avoid zero-length segments.
    
    Args:
        segment_start: Start timestamp in seconds
        segment_end: End timestamp in seconds
        
    Returns:
        Duration in seconds, minimum 1 microsecond
    """
    return max(1e-6, float(segment_end) - float(segment_start))


def _lavfi_input_index(*, has_title: bool, has_logo: bool) -> int:
    """Calculate the input index of `anullsrc` when optional title and/or logo PNGs are appended.
    
    Input order is:
    - 0: Main video
    - 1: Title PNG (if has_title)
    - 2: Logo PNG (if has_title and has_logo, else 1 if has_logo only)
    - N: lavfi audio (last input)
    
    Args:
        has_title: Whether title PNG input is present
        has_logo: Whether logo PNG input is present
        
    Returns:
        Input index for lavfi audio source
    """
    return 1 + (1 if has_title else 0) + (1 if has_logo else 0)
