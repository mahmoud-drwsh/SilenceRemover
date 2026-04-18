"""Command builders for extraction, fallback, and final encode flows."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from src.core.constants import (
    AUDIO_BITRATE,
    FINAL_VIDEO_SOURCE_METADATA_KEY,
    LOGO_OVERLAY_ALPHA,
    LOGO_OVERLAY_MARGIN_PX,
)
from src.ffmpeg.core import add_filter_complex_script, build_ffmpeg_cmd, build_qsv_hwaccel_flags
from src.ffmpeg.encoding_resolver import get_encoder_config
from sr_filter_graph import build_minimal_encode_overlay_filter_complex


def _build_input_command(input_file: Path, *, use_qsv_hardware_path: bool = False) -> list[str]:
    """Build an ffmpeg command with a standard output overwrite flag and input."""
    cmd = build_ffmpeg_cmd(overwrite=True)
    if use_qsv_hardware_path:
        cmd.extend(build_qsv_hwaccel_flags())
    cmd.extend(["-i", str(input_file)])
    return cmd


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
    encoder: str,
    *,
    filter_script_path: Path | None = None,
    title_overlay_path: Path | None = None,
    title_overlay_y: int | None = None,
    logo_path: Path | None = None,
    logo_enabled: bool = False,
    logo_margin_px: int = LOGO_OVERLAY_MARGIN_PX,
    logo_alpha: float = LOGO_OVERLAY_ALPHA,
    source_metadata_filename: str | None = None,
    use_qsv_hardware_path: bool = False,
) -> list[str]:
    """Build a minimal fallback encode command when no audio remains."""
    config = get_encoder_config(encoder)
    codec = config["codec"]
    codec_args = config["args"]

    cmd = _build_input_command(input_file, use_qsv_hardware_path=use_qsv_hardware_path)
    cmd.extend(["-t", "0.1"])

    if title_overlay_path is not None:
        cmd.extend(["-stream_loop", "-1", "-i", str(title_overlay_path)])
    if logo_path is not None:
        cmd.extend(["-stream_loop", "-1", "-i", str(logo_path)])

    if title_overlay_path is not None or logo_path is not None:
        fc = build_minimal_encode_overlay_filter_complex(
            title_overlay_y=title_overlay_y if title_overlay_path is not None else None,
            logo_enabled=logo_enabled if logo_path is not None else False,
            logo_margin_px=logo_margin_px,
            logo_alpha=logo_alpha,
        )
        if filter_script_path is not None:
            add_filter_complex_script(cmd, filter_script_path)
        else:
            cmd.extend(["-filter_complex", fc])
        cmd.extend(["-map", "[outv]", "-map", "0:a?"])

    cmd.extend(["-c:v", codec])
    cmd.extend(codec_args)
    cmd.extend(["-c:a", "aac", "-b:a", AUDIO_BITRATE])
    if source_metadata_filename is not None:
        cmd.extend(["-metadata", f"{FINAL_VIDEO_SOURCE_METADATA_KEY}={source_metadata_filename}"])
    cmd.append(str(output_file))
    return cmd


def build_final_trim_command(
    input_file: Path,
    output_file: Path,
    filter_script_path: Path,
    encoder: str,
    *,
    title_overlay_path: Path | None = None,
    title_overlay_y: int | None = None,
    logo_path: Path | None = None,
    extra_silent_audio_lavfi: bool = False,
    source_metadata_filename: str | None = None,
    video_map_pad: str = "outv",
    use_qsv_hardware_path: bool = False,
    metadata_title: str | None = None,
) -> list[str]:
    """Build final video trim + encode command.

    When ``extra_silent_audio_lavfi`` is True, append a stereo `anullsrc` so the
    filter graph can use ``[1:a]`` (no overlay), ``[2:a]`` (one PNG), or ``[3:a]``
    (title + logo) for silent-audio segment lengths.

    ``video_map_pad`` names the video filter output pad (default ``outv``).
    """
    config = get_encoder_config(encoder)
    codec = config["codec"]
    codec_args = config["args"]

    cmd = _build_input_command(input_file, use_qsv_hardware_path=use_qsv_hardware_path)
    if title_overlay_path is not None:
        cmd.extend(["-stream_loop", "-1", "-i", str(title_overlay_path)])
    if logo_path is not None:
        cmd.extend(["-stream_loop", "-1", "-i", str(logo_path)])
    if extra_silent_audio_lavfi:
        cmd.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
    add_filter_complex_script(cmd, filter_script_path)
    cmd.extend(["-map", f"[{video_map_pad}]", "-map", "[outa]"])
    cmd.extend(["-c:v", codec])
    cmd.extend(codec_args)
    cmd.extend(["-c:a", "aac", "-b:a", AUDIO_BITRATE, "-progress", "pipe:1", "-nostats", "-loglevel", "error"])
    if source_metadata_filename is not None:
        cmd.extend(["-metadata", f"{FINAL_VIDEO_SOURCE_METADATA_KEY}={source_metadata_filename}"])
    if metadata_title is not None:
        cmd.extend(["-metadata", f"title={metadata_title}"])
    cmd.append(str(output_file))
    return cmd
