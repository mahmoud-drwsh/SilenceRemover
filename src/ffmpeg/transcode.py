"""Command builders for extraction, fallback, and final encode flows."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from src.core.constants import AUDIO_BITRATE
from src.ffmpeg.core import add_filter_complex_script, build_ffmpeg_cmd, build_qsv_hwaccel_flags
from src.ffmpeg.encoding_resolver import get_encoder_config


def _build_input_command(input_file: Path, *, use_qsv_hardware_path: bool = False, use_vaapi_hardware_path: bool = False) -> list[str]:
    """Build an ffmpeg command with a standard output overwrite flag and input."""
    cmd = build_ffmpeg_cmd(overwrite=True)
    if use_qsv_hardware_path:
        cmd.extend(build_qsv_hwaccel_flags())
    if use_vaapi_hardware_path:
        cmd.extend(["-vaapi_device", "/dev/dri/renderD128"])
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
    use_qsv_hardware_path: bool = False,
    use_vaapi_hardware_path: bool = False,
) -> list[str]:
    """Build a minimal fallback encode command when no audio remains."""
    config = get_encoder_config(encoder)
    codec = config["codec"]
    codec_args = config["args"]

    cmd = _build_input_command(input_file, use_qsv_hardware_path=use_qsv_hardware_path, use_vaapi_hardware_path=use_vaapi_hardware_path)
    cmd.extend(["-t", "0.1"])
    cmd.extend(["-c:v", codec])
    cmd.extend(codec_args)
    cmd.extend(["-c:a", "aac", "-b:a", AUDIO_BITRATE])
    cmd.append(str(output_file))
    return cmd


def build_final_trim_command(
    input_file: Path,
    output_file: Path,
    filter_script_path: Path,
    encoder: str,
    *,
    extra_silent_audio_lavfi: bool = False,
    video_map_pad: str = "outv",
    use_qsv_hardware_path: bool = False,
    use_vaapi_hardware_path: bool = False,
    metadata_title: str | None = None,
    frame_rate: str | None = None,
) -> list[str]:
    """Build final video trim + encode command.

    When ``extra_silent_audio_lavfi`` is True, append a stereo `anullsrc` so the
    filter graph can use ``[1:a]`` for silent-audio segment lengths.

    ``video_map_pad`` names the video filter output pad (default ``outv``).

    ``frame_rate`` is the source frame rate (for example ``30/1``). The concat
    filter drops the frame rate, and FFmpeg 7 then gives the encoder a 1 MHz time
    base. x265 then writes level 6.x, which many hardware decoders refuse.
    HEVC output gets the ``hvc1`` tag, because Safari does not play ``hev1``.
    """
    config = get_encoder_config(encoder)
    codec = config["codec"]
    codec_args = config["args"]

    cmd = _build_input_command(input_file, use_qsv_hardware_path=use_qsv_hardware_path, use_vaapi_hardware_path=use_vaapi_hardware_path)
    if extra_silent_audio_lavfi:
        cmd.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
    add_filter_complex_script(cmd, filter_script_path)
    cmd.extend(["-map", f"[{video_map_pad}]", "-map", "[outa]"])
    cmd.extend(["-c:v", codec])
    cmd.extend(codec_args)
    if frame_rate is not None:
        cmd.extend(["-fps_mode", "cfr", "-r", frame_rate])
    if "hevc" in codec or codec == "libx265":
        cmd.extend(["-tag:v", "hvc1"])
    cmd.extend(["-movflags", "+faststart"])
    cmd.extend(["-c:a", "aac", "-b:a", AUDIO_BITRATE, "-progress", "pipe:1", "-nostats", "-loglevel", "error"])
    if metadata_title is not None:
        cmd.extend(["-metadata", f"title={metadata_title}"])
    cmd.append(str(output_file))
    return cmd
