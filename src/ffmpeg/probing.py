"""FFmpeg probe helpers for media metadata and encoder capability checks."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from src.core.constants import BITRATE_FALLBACK_BPS
from src.ffmpeg.core import FFMPEG_BIN, FFPROBE_BIN
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
    result = run([FFMPEG_BIN, "-hide_banner", "-encoders"], check=True, capture_output=True)
    return parse_ffmpeg_encoder_lines(result.stdout)


def can_run_encoder(codec: str, codec_args: Sequence[str] = ()) -> bool:
    """Check whether the given codec can run in a minimal encode test."""
    cmd = [
        FFMPEG_BIN,
        "-hide_banner",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=black:s=16x16:d=0.1",
        "-frames:v",
        "1",
        "-c:v",
        codec,
    ]
    cmd.extend(codec_args)
    cmd.extend(["-f", "null", "-"])
    return run(cmd, capture_output=True, check=False).returncode == 0


def probe_duration(input_file: Path) -> float:
    """Probe media duration in seconds."""
    cmd = [
        FFPROBE_BIN,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nw=1:nk=1",
        str(input_file),
    ]
    result = run(cmd, capture_output=True, check=False)
    output = result.stdout.strip()
    try:
        return float(output)
    except (TypeError, ValueError):
        return 0.0


def probe_bitrate_bps(input_file: Path, fallback: int = BITRATE_FALLBACK_BPS) -> int:
    """Probe format-level bitrate and return it in bits-per-second."""
    cmd = [
        FFPROBE_BIN,
        "-v",
        "error",
        "-show_entries",
        "format=bit_rate",
        "-of",
        "default=nw=1:nk=1",
        str(input_file),
    ]
    result = run(cmd, capture_output=True, check=False)
    output = result.stdout.strip()
    if not output:
        return fallback
    try:
        return int(output)
    except (TypeError, ValueError):
        return fallback
