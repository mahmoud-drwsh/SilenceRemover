"""Common utilities for video processing: backward compatibility layer.

This module re-exports all constants and functions from the new modular structure
for backward compatibility. New code should import directly from:
- src.config: Configuration constants
- src.ffmpeg_utils: FFmpeg command building
- src.silence_utils: Silence detection algorithms

Style Guide:
============

This module follows the project's coding standards (see individual modules for details).
"""

# Re-export all constants from config
from src.config import (
    AUDIO_BITRATE,
    BITRATE_FALLBACK_BPS,
    MAX_PAD_SEC,
    OPENROUTER_API_URL,
    OPENROUTER_DEFAULT_MODEL,
    OPENROUTER_TITLE_MODEL,
    PAD_INCREMENT_SEC,
    PREFERRED_VIDEO_ENCODERS,
    TITLE_PROMPT_TEMPLATE,
    TRANSCRIBE_PROMPT,
    VIDEO_EXTENSIONS,
)

# Re-export FFmpeg utilities
from src.ffmpeg_utils import build_ffmpeg_cmd, choose_hwaccel

# Re-export silence detection utilities
from src.silence_utils import (
    calculate_resulting_length,
    detect_silence_points,
    find_optimal_padding,
)

__all__ = [
    # Constants
    "AUDIO_BITRATE",
    "BITRATE_FALLBACK_BPS",
    "MAX_PAD_SEC",
    "OPENROUTER_API_URL",
    "OPENROUTER_DEFAULT_MODEL",
    "OPENROUTER_TITLE_MODEL",
    "PAD_INCREMENT_SEC",
    "PREFERRED_VIDEO_ENCODERS",
    "TITLE_PROMPT_TEMPLATE",
    "TRANSCRIBE_PROMPT",
    "VIDEO_EXTENSIONS",
    # FFmpeg utilities
    "build_ffmpeg_cmd",
    "choose_hwaccel",
    # Silence detection utilities
    "calculate_resulting_length",
    "detect_silence_points",
    "find_optimal_padding",
]
