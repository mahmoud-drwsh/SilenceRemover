"""FFmpeg probe helpers for media metadata and encoder capability checks."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Sequence

from src.core.constants import BITRATE_FALLBACK_BPS
from src.ffmpeg.core import build_ffmpeg_cmd, build_ffprobe_cmd
from src.ffmpeg.runner import run

_ENCODER_LINE_RE = re.compile(r"^\s*[.A-Z]{6}\s+\S+")


def parse_ffmpeg_encoder_lines(output: str) -> set[str]:
    """Extract encoder names from `ffmpeg -encoders` output."""
    encoders: set[str] = set()
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue
        if _ENCODER_LINE_RE.match(raw_line) is None:
            continue
        parts = raw_line.split()
        encoder_name = parts[1] if len(parts) > 1 else ""
        if encoder_name:
            encoders.add(encoder_name)
    return encoders


def get_available_encoders() -> set[str]:
    """Return supported encoder names from the current FFmpeg installation."""
    cmd = build_ffmpeg_cmd(overwrite=False, "-encoders")
    result = run(cmd, check=True, capture_output=True)
    return parse_ffmpeg_encoder_lines(result.stdout)


def build_encoder_probe_command(codec: str, codec_args: Sequence[str] = ()) -> list[str]:
    """Build a probe command for encoding tests."""
    cmd = build_ffmpeg_cmd(
        overwrite=False,
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=black:s=64x64:d=0.4",
        "-frames:v",
        "4",
        "-c:v",
        codec,
        "-pix_fmt",
        "nv12",
    )
    if codec == "hevc_qsv":
        cmd.extend(["-g", "1", "-bf", "0"])
    cmd.extend(codec_args)
    cmd.extend(["-f", "null", "-"])
    return cmd


def build_ffprobe_metadata_command(input_file: Path, format_entry: str) -> list[str]:
    """Build a simple ffprobe format field query command."""
    return build_ffprobe_cmd(
        "-v",
        "error",
        "-show_entries",
        f"format={format_entry}",
        "-of",
        "default=nw=1:nk=1",
        str(input_file),
    )


def run_ffprobe_float(input_file: Path, format_entry: str, fallback: float) -> float:
    """Run ffprobe and parse a float metadata field."""
    result = run(build_ffprobe_metadata_command(input_file, format_entry), capture_output=True, check=False)
    output = result.stdout.strip()
    try:
        return float(output)
    except (TypeError, ValueError):
        return fallback


def can_run_encoder(codec: str, codec_args: Sequence[str] = ()) -> bool:
    """Check whether the given codec can run in a minimal encode test."""
    cmd = build_encoder_probe_command(codec, codec_args)
    result = run(cmd, capture_output=True, check=False)
    if result.returncode != 0:
        quoted_cmd = " ".join(shlex.quote(arg) for arg in cmd)
        print(f"FFmpeg probe failed for codec={codec}:")
        print(f"  Command: {quoted_cmd}")
        print(f"  Return code: {result.returncode}")
        if result.stderr:
            print(f"  Stderr: {result.stderr.strip()}")
        return False
    return True


def probe_duration(input_file: Path) -> float:
    """Probe media duration in seconds."""
    return run_ffprobe_float(input_file, "duration", 0.0)


def probe_bitrate_bps(input_file: Path, fallback: int = BITRATE_FALLBACK_BPS) -> int:
    """Probe format-level bitrate and return it in bits-per-second."""
    result = run_ffprobe_float(input_file, "bit_rate", float(fallback))
    if result == float(fallback):
        return fallback
    try:
        return int(result)
    except (TypeError, ValueError):
        return fallback
