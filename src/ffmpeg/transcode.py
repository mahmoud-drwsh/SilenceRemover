"""Command builders for extraction, fallback, and final encode flows."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, TYPE_CHECKING

from src.core.constants import AUDIO_BITRATE, SNIPPET_MAX_DURATION_SEC
from src.ffmpeg.core import add_filter_complex_script, build_ffmpeg_cmd

if TYPE_CHECKING:
    from src.ffmpeg.encoding_resolver import VideoEncoderProfile


def build_audio_window_extract_command(
    input_file: Path,
    output_audio: Path,
    *,
    start_seconds: float = 0.0,
    duration_seconds: float = SNIPPET_MAX_DURATION_SEC,
    codec_args: Sequence[str] | None = None,
) -> list[str]:
    """Build a fixed-window audio extraction command."""
    cmd = build_ffmpeg_cmd(overwrite=True)
    cmd.extend(["-ss", str(start_seconds), "-t", str(duration_seconds), "-i", str(input_file), "-map", "0:a:0"])
    if codec_args:
        cmd.extend(codec_args)
    cmd.extend(["-vn", str(output_audio)])
    return cmd


def build_first_5min_audio_ogg_command(input_video: Path, output_audio: Path) -> list[str]:
    """Build Ogg/Opus extraction command for the first five minutes."""
    return build_audio_window_extract_command(
        input_file=input_video,
        output_audio=output_audio,
        codec_args=[
            "-c:a",
            "libopus",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-b:a",
            "32k",
        ],
    )


def build_first_5min_audio_copy_command(input_video: Path, output_audio: Path) -> list[str]:
    """Build copy-first extraction command."""
    return build_audio_window_extract_command(
        input_file=input_video,
        output_audio=output_audio,
        codec_args=["-c:a", "copy"],
    )


def build_first_5min_audio_aac_command(input_video: Path, output_audio: Path) -> list[str]:
    """Build AAC fallback extraction command."""
    return build_audio_window_extract_command(
        input_file=input_video,
        output_audio=output_audio,
        codec_args=["-c:a", "aac", "-b:a", AUDIO_BITRATE],
    )


def build_minimal_audio_command(input_file: Path, output_audio: Path, codec_args: Sequence[str]) -> list[str]:
    """Build a short fallback audio extraction command."""
    cmd = build_ffmpeg_cmd(overwrite=True)
    cmd.extend(["-i", str(input_file), "-t", "0.1"])
    cmd.extend(codec_args)
    cmd.extend(["-vn", str(output_audio)])
    return cmd


def build_silence_removed_audio_command(
    input_file: Path,
    output_audio_path: Path,
    filter_script_path: Path,
    *,
    acodec: Sequence[str],
    max_duration: float | None = None,
) -> list[str]:
    """Build audio-only silence-removed output command."""
    cmd = build_ffmpeg_cmd(overwrite=True)
    cmd.extend(["-i", str(input_file), "-vn"])
    add_filter_complex_script(cmd, filter_script_path)
    cmd.extend(["-map", "[outa]"])
    cmd.extend(acodec)
    if max_duration is not None:
        cmd.extend(["-t", str(max_duration)])
    cmd.append(str(output_audio_path))
    return cmd


def build_minimal_video_command(input_file: Path, output_file: Path, encoder: "VideoEncoderProfile") -> list[str]:
    """Build a minimal fallback encode command when no audio remains."""
    cmd = build_ffmpeg_cmd(overwrite=True)
    cmd.extend(["-i", str(input_file), "-t", "0.1"])
    cmd.extend(encoder.video_args())
    cmd.extend(["-c:a", "aac", "-b:a", AUDIO_BITRATE, str(output_file)])
    return cmd


def build_final_trim_command(
    input_file: Path,
    output_file: Path,
    filter_script_path: Path,
    encoder: "VideoEncoderProfile",
) -> list[str]:
    """Build final video trim + encode command."""
    cmd = build_ffmpeg_cmd(overwrite=True)
    cmd.extend(["-i", str(input_file)])
    add_filter_complex_script(cmd, filter_script_path)
    cmd.extend(["-map", "[outv]", "-map", "[outa]"])
    cmd.extend(encoder.video_args(include_container_args=True))
    cmd.extend(["-c:a", "aac", "-b:a", AUDIO_BITRATE, "-progress", "pipe:1", "-nostats", "-loglevel", "error"])
    cmd.append(str(output_file))
    return cmd
