"""FFmpeg silence detection black box package.

Provides clean APIs for detecting silence intervals without exposing
FFmpeg implementation details.

Public API:
- detect_silence(): Single-pass silence detection
- detect_silence_with_edges(): Edge-aware detection with buffer preservation
- detect_edge_only_cached(): Edge detection with file-based caching
- detect_primary_with_cached_edges(): Primary detection with pre-computed edge intervals
"""

from sr_silence_detection.api import (
    detect_edge_only_cached,
    detect_primary_with_cached_edges,
    detect_silence,
    detect_silence_with_edges,
)

__all__ = [
    "detect_silence",
    "detect_silence_with_edges",
    "detect_edge_only_cached",
    "detect_primary_with_cached_edges",
]
