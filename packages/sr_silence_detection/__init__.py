"""FFmpeg silence detection black box package.

Provides clean APIs for detecting silence intervals without exposing
FFmpeg implementation details.

Public API:
- detect_silence(): Single-pass silence detection
- detect_silence_with_edges(): Edge-aware detection with buffer preservation
- detect_edge_only_cached(): Edge detection with file-based caching
- detect_primary_with_cached_edges(): Primary detection with pre-computed edge intervals

Cache utilities (optional):
- get_cached_primary_detection(): Read cached primary detection results
- save_primary_detection(): Write primary detection results to cache
"""

from sr_silence_detection._cache import (
    get_cached_primary_detection,
    save_primary_detection,
)
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
    "get_cached_primary_detection",
    "save_primary_detection",
]
