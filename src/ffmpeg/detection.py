"""Silence detection command builders and parsers."""

from __future__ import annotations

import re
from pathlib import Path
import subprocess

from src.ffmpeg.core import build_ffmpeg_cmd, print_ffmpeg_cmd
from src.ffmpeg.runner import run


def build_silence_detection_command(input_file: Path, noise_threshold: float, min_duration: float) -> list[str]:
    """Build FFmpeg command for silence detection."""
    silence_filter = f"silencedetect=n={noise_threshold}dB:d={min_duration}"
    cmd = build_ffmpeg_cmd(overwrite=True)
    cmd.extend(["-vn", "-sn", "-dn", "-i", str(input_file), "-map", "0:a:0", "-af", silence_filter, "-f", "null", "-"])
    return cmd


def parse_silence_output(result: str) -> tuple[list[float], list[float]]:
    """Parse silencedetect output into silence start/end lists."""
    silence_starts = [float(x) for x in re.findall(r"silence_start: (-?\d+\.?\d*)", result)]
    silence_ends = [float(x) for x in re.findall(r"silence_end: (\d+\.?\d*)", result)]
    return silence_starts, silence_ends


def detect_silence_points(input_file: Path, noise_threshold: float, min_duration: float) -> tuple[list[float], list[float]]:
    """Detect silence start/end points via FFmpeg's silencedetect filter."""
    cmd = build_silence_detection_command(input_file, noise_threshold, min_duration)
    print_ffmpeg_cmd(cmd)
    result = run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, check=True)
    return parse_silence_output(result.stderr)

