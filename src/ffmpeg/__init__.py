"""Centralized FFmpeg orchestration package."""

from src.ffmpeg.types import ExecutionMode, RunnerOptions
from src.ffmpeg.core import FFMPEG_BIN, FFPROBE_BIN, add_filter_complex_script, build_ffmpeg_cmd, build_ffprobe_cmd, print_ffmpeg_cmd
from src.ffmpeg.detection import detect_silence_points
from src.ffmpeg.filter_graph import (
    build_audio_concat_filter_graph,
    build_filter_graph_script,
    build_video_audio_concat_filter_graph,
    write_filter_graph_script,
)
from src.ffmpeg.probing import (
    BITRATE_FALLBACK_BPS,
    can_run_encoder,
    get_available_encoders,
    probe_bitrate_bps,
    probe_duration,
)
from src.ffmpeg.runner import run, run_with_progress
from src.ffmpeg.transcode import (
    build_audio_window_extract_command,
    build_first_5min_audio_aac_command,
    build_first_5min_audio_copy_command,
    build_first_5min_audio_ogg_command,
    build_final_trim_command,
    build_minimal_audio_command,
    build_minimal_video_command,
    build_silence_removed_audio_command,
)
from src.ffmpeg.encoding_resolver import VideoEncoderProfile, resolve_video_encoder

__all__ = [
    "FFMPEG_BIN",
    "FFPROBE_BIN",
    "add_filter_complex_script",
    "build_ffmpeg_cmd",
    "build_ffprobe_cmd",
    "print_ffmpeg_cmd",
    "detect_silence_points",
    "build_audio_concat_filter_graph",
    "build_filter_graph_script",
    "build_video_audio_concat_filter_graph",
    "write_filter_graph_script",
    "BITRATE_FALLBACK_BPS",
    "can_run_encoder",
    "get_available_encoders",
    "probe_bitrate_bps",
    "probe_duration",
    "ExecutionMode",
    "RunnerOptions",
    "run",
    "run_with_progress",
    "build_audio_window_extract_command",
    "build_first_5min_audio_aac_command",
    "build_first_5min_audio_copy_command",
    "build_first_5min_audio_ogg_command",
    "build_final_trim_command",
    "build_minimal_audio_command",
    "build_minimal_video_command",
    "build_silence_removed_audio_command",
    "VideoEncoderProfile",
    "resolve_video_encoder",
]
