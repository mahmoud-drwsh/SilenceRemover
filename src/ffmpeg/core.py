"""Core FFmpeg/FFprobe command utilities."""

from __future__ import annotations

import shlex
from pathlib import Path

FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"


def build_ffmpeg_cmd(overwrite: bool = True, *additional_flags: str) -> list[str]:
    """Build a base FFmpeg command with common flags.

    Args:
        overwrite: Add -y when True so outputs are overwritten.
        *additional_flags: Additional positional FFmpeg flags to append.

    Returns:
        List of command tokens beginning with ffmpeg.
    """
    cmd = [FFMPEG_BIN, "-hide_banner"]
    if overwrite:
        cmd.append("-y")
    cmd.extend(additional_flags)
    return cmd


def build_qsv_hwaccel_flags(device_name: str = "qsv") -> list[str]:
    """Build optional FFmpeg flags for a QSV-oriented hardware path."""
    return [
        "-init_hw_device",
        f"qsv={device_name}",
        "-filter_hw_device",
        device_name,
        "-hwaccel",
        "qsv",
        "-hwaccel_output_format",
        "qsv",
    ]


def build_ffprobe_cmd(*args: str) -> list[str]:
    """Build a base FFprobe command."""
    return [FFPROBE_BIN, *args]


def add_filter_complex_script(cmd: list[str], filter_script_path: Path) -> None:
    """Attach a filter graph script using FFmpeg's modern non-deprecated option."""
    cmd.extend(["-/filter_complex", str(filter_script_path)])


def print_ffmpeg_cmd(cmd: list[str]) -> None:
    """Print an FFmpeg command in shell-friendly quoting."""
    if not cmd or cmd[0] != FFMPEG_BIN:
        return
    quoted = [shlex.quote(str(arg)) for arg in cmd]
    print("FFmpeg:", " ".join(quoted))
