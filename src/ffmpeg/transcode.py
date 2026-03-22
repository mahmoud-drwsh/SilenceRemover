"""Command builders for extraction, fallback, and final encode flows."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, TYPE_CHECKING

from src.core.constants import (
    AUDIO_BITRATE,
    FINAL_VIDEO_SOURCE_METADATA_KEY,
    SNIPPET_MAX_DURATION_SEC,
)
from src.ffmpeg.core import add_filter_complex_script, build_ffmpeg_cmd

if TYPE_CHECKING:
    from src.ffmpeg.encoding_resolver import VideoEncoderProfile


def _build_input_command(input_file: Path) -> list[str]:
    """Build an ffmpeg command with a standard output overwrite flag and input."""
    cmd = build_ffmpeg_cmd(overwrite=True)
    cmd.extend(["-i", str(input_file)])
    return cmd


def _build_input_command_with_options(input_file: Path, *ffmpeg_options: str) -> list[str]:
    """Build an ffmpeg command with options that must appear before the input."""
    cmd = build_ffmpeg_cmd(overwrite=True)
    cmd.extend(ffmpeg_options)
    cmd.extend(["-i", str(input_file)])
    return cmd


def build_audio_window_extract_command(
    input_file: Path,
    output_audio: Path,
    *,
    start_seconds: float = 0.0,
    duration_seconds: float = SNIPPET_MAX_DURATION_SEC,
    codec_args: Sequence[str] | None = None,
) -> list[str]:
    """Build a fixed-window audio extraction command."""
    cmd = _build_input_command_with_options(
        input_file,
        "-ss",
        str(start_seconds),
        "-t",
        str(duration_seconds),
    )
    cmd.extend(["-map", "0:a:0"])
    if codec_args:
        cmd.extend(codec_args)
    cmd.extend(["-vn", str(output_audio)])
    return cmd


def build_first_5min_audio_ogg_command(input_video: Path, output_audio: Path) -> list[str]:
    """Build Ogg/Opus extraction for an opening window (default duration: `SNIPPET_MAX_DURATION_SEC`)."""
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


def build_silent_audio_file_command(
    output_audio: Path,
    duration_sec: float,
    codec_args: Sequence[str],
) -> list[str]:
    """Encode silent audio of `duration_sec` (e.g. when the source has no audio stream)."""
    cmd = build_ffmpeg_cmd(overwrite=True)
    cmd.extend(["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", str(duration_sec)])
    cmd.extend(list(codec_args))
    cmd.append(str(output_audio))
    return cmd


def build_minimal_audio_command(input_file: Path, output_audio: Path, codec_args: Sequence[str]) -> list[str]:
    """Build a short fallback audio extraction command."""
    cmd = _build_input_command(input_file)
    cmd.extend(["-t", "0.1"])
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
    cmd = _build_input_command(input_file)
    cmd.extend(["-vn"])
    add_filter_complex_script(cmd, filter_script_path)
    cmd.extend(["-map", "[outa]"])
    cmd.extend(acodec)
    if max_duration is not None:
        cmd.extend(["-t", str(max_duration)])
    cmd.append(str(output_audio_path))
    return cmd


def build_minimal_video_command(
    input_file: Path,
    output_file: Path,
    encoder: "VideoEncoderProfile",
    *,
    title_overlay_path: Path | None = None,
    title_overlay_y: int | None = None,
    source_metadata_filename: str | None = None,
) -> list[str]:
    """Build a minimal fallback encode command when no audio remains."""
    cmd = _build_input_command(input_file)
    cmd.extend(["-t", "0.1"])

    if title_overlay_path is not None:
        cmd.extend(["-stream_loop", "-1", "-i", str(title_overlay_path)])
        overlay_y_str = str(title_overlay_y) if title_overlay_y is not None else "0"
        cmd.extend(
            [
                "-filter_complex",
                f"[0:v][1:v]overlay=0:{overlay_y_str}:shortest=1[outv]",
                "-map",
                "[outv]",
                "-map",
                "0:a?",
            ]
        )

    cmd.extend(encoder.video_args())
    cmd.extend(["-c:a", "aac", "-b:a", AUDIO_BITRATE])
    if source_metadata_filename is not None:
        cmd.extend(["-metadata", f"{FINAL_VIDEO_SOURCE_METADATA_KEY}={source_metadata_filename}"])
    cmd.append(str(output_file))
    return cmd


def build_final_trim_command(
    input_file: Path,
    output_file: Path,
    filter_script_path: Path,
    encoder: "VideoEncoderProfile",
    *,
    title_overlay_path: Path | None = None,
    title_overlay_y: int | None = None,
    extra_silent_audio_lavfi: bool = False,
    source_metadata_filename: str | None = None,
) -> list[str]:
    """Build final video trim + encode command.

    When ``extra_silent_audio_lavfi`` is True, append a stereo `anullsrc` so the
    filter graph can use ``[1:a]`` (no overlay) or ``[2:a]`` (with PNG overlay) for audio.
    """
    cmd = _build_input_command(input_file)
    if title_overlay_path is not None:
        cmd.extend(["-stream_loop", "-1", "-i", str(title_overlay_path)])
    if extra_silent_audio_lavfi:
        cmd.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
    add_filter_complex_script(cmd, filter_script_path)
    cmd.extend(["-map", "[outv]", "-map", "[outa]"])
    cmd.extend(encoder.video_args(include_container_args=True))
    cmd.extend(["-c:a", "aac", "-b:a", AUDIO_BITRATE, "-progress", "pipe:1", "-nostats", "-loglevel", "error"])
    if source_metadata_filename is not None:
        cmd.extend(["-metadata", f"{FINAL_VIDEO_SOURCE_METADATA_KEY}={source_metadata_filename}"])
    cmd.append(str(output_file))
    return cmd
