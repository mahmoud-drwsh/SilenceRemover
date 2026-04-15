"""Internal: Run FFmpeg silence detection and return parsed intervals."""

from __future__ import annotations

from pathlib import Path

from src.ffmpeg.probing import probe_duration, probe_has_audio_stream
from src.ffmpeg.runner import run

from sr_silence_detection._ffmpeg_commands import (
    _build_dual_silence_detection_command,
    _build_silence_detection_command,
)
from sr_silence_detection._parsers import _parse_dual_silence_output, _parse_silence_output


def _detect_raw(input_file: Path, noise_threshold: float, min_duration: float) -> tuple[list[float], list[float]]:
    """Detect silence start/end points via FFmpeg's silencedetect filter."""
    if not probe_has_audio_stream(input_file):
        return [], []

    cmd = _build_silence_detection_command(input_file, noise_threshold, min_duration)
    result = run(cmd, capture_output=True, text=True, check=True)
    return _parse_silence_output(result.stderr)


def _detect_dual_raw(
    input_file: Path,
    primary_noise_threshold: float,
    primary_min_duration: float,
    edge_noise_threshold: float,
    edge_min_duration: float,
) -> tuple[tuple[list[float], list[float]], tuple[list[float], list[float]]]:
    """Run primary and edge silencedetect in one FFmpeg invocation (one audio decode)."""
    if not probe_has_audio_stream(input_file):
        return ([], []), ([], [])

    cmd = _build_dual_silence_detection_command(
        input_file,
        primary_noise_threshold,
        primary_min_duration,
        edge_noise_threshold,
        edge_min_duration,
    )
    result = run(cmd, capture_output=True, text=True, check=True)
    primary, edge, ok = _parse_dual_silence_output(result.stderr)
    if not ok:
        # No per-filter pointers (e.g. neither filter logged) — avoid two more full decodes when stderr has no silence lines.
        err = result.stderr
        if "silence_start:" not in err and "silence_end:" not in err:
            return ([], []), ([], [])
        primary = _detect_raw(input_file, primary_noise_threshold, primary_min_duration)
        edge = _detect_raw(input_file, edge_noise_threshold, edge_min_duration)
        return primary, edge
    return primary, edge


def _probe_duration_safe(input_file: Path) -> float:
    """Probe media duration, ensuring a valid positive value."""
    duration = probe_duration(input_file)
    if duration <= 0:
        raise ValueError(f"Invalid video duration: {duration}s. Video file may be corrupted or empty.")
    return duration
