"""FFmpeg/FFprobe command building utilities (pure functions).

This package provides pure functions for constructing FFmpeg and FFprobe
command arrays. No subprocess calls, no file I/O - just command assembly.
"""

from sr_ffmpeg_cmd_builder._encoding import build_encoder_probe_command
from sr_ffmpeg_cmd_builder._probing import (
    build_ffprobe_format_json_command,
    build_ffprobe_has_audio_command,
    build_ffprobe_metadata_command,
    build_ffprobe_stream_dimensions_command,
)

__all__ = [
    "build_encoder_probe_command",
    "build_ffprobe_format_json_command",
    "build_ffprobe_has_audio_command",
    "build_ffprobe_metadata_command",
    "build_ffprobe_stream_dimensions_command",
]
