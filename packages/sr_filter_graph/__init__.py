"""FFmpeg filter graph building utilities (pure algorithm package).

This package provides pure functions for building FFmpeg filter graph strings.
No file I/O, no subprocess calls - just data transformation.
"""

from sr_filter_graph._concat import (
    build_audio_concat_filter_graph,
    build_filter_graph_script,
    build_video_audio_concat_filter_graph,
    build_video_lavfi_audio_concat_filter_graph,
)
from sr_filter_graph._core import _segment_audio_duration_sec
from sr_filter_graph._escaping import _escape_ffmpeg_single_quoted_path

__all__ = [
    # Core concat builders
    "build_audio_concat_filter_graph",
    "build_filter_graph_script",
    "build_video_audio_concat_filter_graph",
    "build_video_lavfi_audio_concat_filter_graph",
    # Utility functions (for advanced use)
    "_segment_audio_duration_sec",
    "_escape_ffmpeg_single_quoted_path",
]
