"""Silence detection command builders and parsers."""

from __future__ import annotations

import re
from pathlib import Path

from src.ffmpeg.core import build_ffmpeg_cmd, print_ffmpeg_cmd
from src.ffmpeg.probing import probe_has_audio_stream
from src.ffmpeg.runner import run


def build_silence_detection_command(input_file: Path, noise_threshold: float, min_duration: float) -> list[str]:
    """Build FFmpeg command for silence detection."""
    silence_filter = f"silencedetect=n={noise_threshold}dB:d={min_duration}"
    cmd = build_ffmpeg_cmd(overwrite=True)
    cmd.extend(["-vn", "-sn", "-dn", "-i", str(input_file), "-map", "0:a:0", "-af", silence_filter, "-f", "null", "-"])
    return cmd


def build_dual_silence_detection_command(
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


def parse_silence_output(result: str) -> tuple[list[float], list[float]]:
    """Parse silencedetect output into silence start/end lists."""
    silence_starts = [float(x) for x in re.findall(r"silence_start: (-?\d+\.?\d*)", result)]
    silence_ends = [float(x) for x in re.findall(r"silence_end: (\d+\.?\d*)", result)]
    return silence_starts, silence_ends


def parse_dual_silence_output(stderr: str) -> tuple[tuple[list[float], list[float]], tuple[list[float], list[float]], bool]:
    """Split stderr from a chained dual silencedetect filter into (primary, edge) interval lists.

    FFmpeg tags each filter instance with ``[silencedetect @ 0x...]``; we bucket by pointer in
    order of first appearance (matches filter chain order: primary then edge).

    Returns ``(primary, edge, ok)``. If fewer than two distinct filter pointers appear in the log
    (e.g. one filter emitted no lines), ``ok`` is False and callers should fall back to two
    separate ``detect_silence_points`` runs.
    """
    ptr_order: list[str] = []
    seen: set[str] = set()
    for line in stderr.splitlines():
        m = re.search(r"\[silencedetect @ (0x[0-9a-fA-F]+)\]", line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            ptr_order.append(m.group(1))

    if len(ptr_order) < 2:
        return ([], []), ([], []), False

    ptr_to_bucket = {p: i for i, p in enumerate(ptr_order[:2])}

    starts: list[list[float]] = [[], []]
    ends: list[list[float]] = [[], []]
    start_re = re.compile(r"silence_start: (-?\d+\.?\d*)")
    end_re = re.compile(r"silence_end: (\d+\.?\d*)")
    for line in stderr.splitlines():
        m = re.search(r"\[silencedetect @ (0x[0-9a-fA-F]+)\]", line)
        if not m:
            continue
        bi = ptr_to_bucket.get(m.group(1))
        if bi is None:
            continue
        sm = start_re.search(line)
        if sm:
            starts[bi].append(float(sm.group(1)))
        em = end_re.search(line)
        if em:
            ends[bi].append(float(em.group(1)))

    return (starts[0], ends[0]), (starts[1], ends[1]), True


def detect_primary_and_edge_silence_points(
    input_file: Path,
    primary_noise_threshold: float,
    primary_min_duration: float,
    edge_noise_threshold: float,
    edge_min_duration: float,
) -> tuple[tuple[list[float], list[float]], tuple[list[float], list[float]]]:
    """Run primary and edge silencedetect in one FFmpeg invocation (one audio decode)."""
    if not probe_has_audio_stream(input_file):
        return ([], []), ([], [])

    cmd = build_dual_silence_detection_command(
        input_file,
        primary_noise_threshold,
        primary_min_duration,
        edge_noise_threshold,
        edge_min_duration,
    )
    print_ffmpeg_cmd(cmd)
    result = run(cmd, capture_output=True, text=True, check=True)
    primary, edge, ok = parse_dual_silence_output(result.stderr)
    if not ok:
        # No per-filter pointers (e.g. neither filter logged) — avoid two more full decodes when stderr has no silence lines.
        err = result.stderr
        if "silence_start:" not in err and "silence_end:" not in err:
            return ([], []), ([], [])
        primary = detect_silence_points(input_file, primary_noise_threshold, primary_min_duration)
        edge = detect_silence_points(input_file, edge_noise_threshold, edge_min_duration)
        return primary, edge
    return primary, edge


def detect_silence_points(input_file: Path, noise_threshold: float, min_duration: float) -> tuple[list[float], list[float]]:
    """Detect silence start/end points via FFmpeg's silencedetect filter."""
    if not probe_has_audio_stream(input_file):
        return [], []

    cmd = build_silence_detection_command(input_file, noise_threshold, min_duration)
    print_ffmpeg_cmd(cmd)
    result = run(cmd, capture_output=True, text=True, check=True)
    return parse_silence_output(result.stderr)
