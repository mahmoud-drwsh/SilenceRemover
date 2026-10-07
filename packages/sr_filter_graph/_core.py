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
