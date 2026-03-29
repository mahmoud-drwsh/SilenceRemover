"""Internal: FFmpeg command builders for silence detection."""

from __future__ import annotations

from pathlib import Path

from src.ffmpeg.core import build_ffmpeg_cmd


def _build_silence_detection_command(input_file: Path, noise_threshold: float, min_duration: float) -> list[str]:
    """Build FFmpeg command for silence detection."""
    silence_filter = f"silencedetect=n={noise_threshold}dB:d={min_duration}"
    cmd = build_ffmpeg_cmd(overwrite=True)
    cmd.extend(["-vn", "-sn", "-dn", "-i", str(input_file), "-map", "0:a:0", "-af", silence_filter, "-f", "null", "-"])
    return cmd


def _build_dual_silence_detection_command(
    input_file: Path,
    primary_noise_threshold: float,
    primary_min_duration: float,
    edge_noise_threshold: float,
    edge_min_duration: float,
) -> list[str]:
    """Single decode with two chained silencedetect filters (primary policy + edge re-scan)."""
    f_primary = f"silencedetect=n={primary_noise_threshold}dB:d={primary_min_duration}"
    f_edge = f"silencedetect=n={edge_noise_threshold}dB:d={edge_min_duration}"
    chain = f"{f_primary},{f_edge}"
    cmd = build_ffmpeg_cmd(overwrite=True)
    cmd.extend(["-vn", "-sn", "-dn", "-i", str(input_file), "-map", "0:a:0", "-af", chain, "-f", "null", "-"])
    return cmd
