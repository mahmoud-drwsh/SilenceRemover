"""Silence detection and trimming algorithm utilities."""

import re
import subprocess
from pathlib import Path

from src.config import MAX_PAD_SEC, PAD_INCREMENT_SEC
from src.ffmpeg_utils import build_ffmpeg_cmd, print_ffmpeg_cmd


def calculate_resulting_length(silence_starts: list[float], silence_ends: list[float], duration_sec: float, pad_sec: float) -> float:
    """Calculate the resulting video length after trimming silences with padding.
    
    Args:
        silence_starts: List of silence start times in seconds
        silence_ends: List of silence end times in seconds
        duration_sec: Total video duration in seconds
        pad_sec: Padding to retain around silences in seconds
        
    Returns:
        Total length of segments to keep in seconds
    """
    if len(silence_starts) != len(silence_ends):
        if len(silence_starts) > len(silence_ends):
            silence_ends = list(silence_ends) + [duration_sec]
        else:
            silence_ends = list(silence_ends)
    segments_to_keep: list[tuple[float, float]] = []
    prev_end = 0.0
    for silence_start, silence_end in zip(silence_starts, silence_ends):
        if silence_end - silence_start <= pad_sec * 2:
            continue
        if silence_start > prev_end:
            segment_start = round(prev_end, 3)
            segment_end = round(silence_start, 3)
            segments_to_keep.append((segment_start, segment_end))
        prev_end = max(0.0, silence_end - pad_sec)
    if prev_end < duration_sec:
        segments_to_keep.append((round(prev_end, 3), round(duration_sec, 3)))
    return sum(end - start for start, end in segments_to_keep)


def find_optimal_padding(silence_starts: list[float], silence_ends: list[float], duration_sec: float, target_length: float) -> float:
    """Find the optimal padding value to achieve a target video length.
    
    Args:
        silence_starts: List of silence start times in seconds
        silence_ends: List of silence end times in seconds
        duration_sec: Total video duration in seconds
        target_length: Desired resulting video length in seconds
        
    Returns:
        Optimal padding value in seconds
    """
    if not silence_starts:
        return 0.0
    result_with_0 = calculate_resulting_length(silence_starts, silence_ends, duration_sec, 0.0)
    if target_length >= duration_sec:
        return 0.0
    if result_with_0 > target_length:
        return 0.0
    max_pad = MAX_PAD_SEC
    pad_increment = PAD_INCREMENT_SEC
    current_pad = 0.0
    best_pad = 0.0
    while current_pad <= max_pad:
        resulting_length = calculate_resulting_length(silence_starts, silence_ends, duration_sec, current_pad)
        if resulting_length < target_length:
            best_pad = current_pad
        else:
            break
        current_pad += pad_increment
    return round(best_pad, 3)


def detect_silence_points(input_file: Path, noise_threshold: float, min_duration: float, debug: bool = False) -> tuple[list[float], list[float]]:
    """Detect silence points in a video file using FFmpeg's silencedetect filter.
    
    Args:
        input_file: Path to input video file
        noise_threshold: Noise threshold in dB for silence detection
        min_duration: Minimum duration in seconds for a silence to be detected
        debug: If True, print debug information
        
    Returns:
        Tuple of (silence_starts, silence_ends) lists in seconds
    """
    silence_filter = f"silencedetect=n={noise_threshold}dB:d={min_duration}"

    cmd = build_ffmpeg_cmd(overwrite=True)
    # Audio-only analysis: skip video/subtitle/data decoding for speed
    cmd.extend(["-vn", "-sn", "-dn", "-i", str(input_file), "-map", "0:a:0", "-af", silence_filter, "-f", "null", "-"])

    print_ffmpeg_cmd(cmd)
    result = subprocess.run(
        cmd,
        stderr=subprocess.PIPE,
        text=True,
    ).stderr
    if debug:
        print(f"[debug] silencedetect filter: {silence_filter}")
        print(f"[debug] ffmpeg cmd: {' '.join(cmd)}")
        print(f"[debug] Raw FFmpeg silencedetect output (showing lines with 'silence_'):")
        for line in result.splitlines():
            if "silence_" in line:
                print(f"[debug] {line}")
    silence_starts = [float(x) for x in re.findall(r"silence_start: (-?\d+\.?\d*)", result)]
    silence_ends = [float(x) for x in re.findall(r"silence_end: (\d+\.?\d*)", result)]
    if debug:
        print(f"[debug] Parsed counts: starts={len(silence_starts)} ends={len(silence_ends)}")
        if silence_starts:
            print(f"[debug] First start={silence_starts[0]} last start={silence_starts[-1]}")
        if silence_ends:
            print(f"[debug] First end  ={silence_ends[0]} last end  ={silence_ends[-1]}")
        print(f"[debug] Parsed silence_starts={silence_starts[:10]}{'...' if len(silence_starts)>10 else ''}")
        print(f"[debug] Parsed silence_ends  ={silence_ends[:10]}{'...' if len(silence_ends)>10 else ''}")
    return silence_starts, silence_ends
