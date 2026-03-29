"""FFmpeg silence detection black box package.

Provides clean APIs for detecting silence intervals without exposing
FFmpeg implementation details.

Public API:
- detect_silence(): Single-pass silence detection
- detect_silence_with_edges(): Edge-aware detection with buffer preservation
"""

from sr_silence_detection.api import detect_silence, detect_silence_with_edges

__all__ = ["detect_silence", "detect_silence_with_edges"]
