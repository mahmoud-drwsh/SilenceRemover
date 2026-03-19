"""Video trimming functionality."""

import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from src.core.constants import (
    SCRIPTS_DIR,
    SNIPPET_MAX_DURATION_SEC,
    SNIPPET_MIN_DURATION_SEC,
    SNIPPET_NOISE_THRESHOLD_DB,
    TARGET_MIN_DURATION_SEC,
    TRIM_TIMESTAMP_EPSILON_SEC,
)
from src.ffmpeg.encoding_resolver import VideoEncoderProfile, resolve_video_encoder
from src.ffmpeg.core import print_ffmpeg_cmd
from src.ffmpeg.filter_graph import (
    build_audio_concat_filter_graph,
    build_video_audio_concat_filter_graph,
    write_filter_graph_script,
)
from src.ffmpeg.probing import probe_duration
from src.ffmpeg.runner import run, run_with_progress
from src.ffmpeg.transcode import (
    build_final_trim_command,
    build_minimal_audio_command,
    build_minimal_video_command,
    build_silence_removed_audio_command,
)
from src.core.fs_utils import wait_for_file_release
from src.media.silence_detector import (
    choose_threshold_and_padding_for_target,
    detect_leading_trailing_edge_silence,
    detect_silence_points,
    normalize_timestamp,
    replace_edge_intervals,
    trim_edge_silence,
)


def _build_segments_from_silences(
    silence_starts: list[float],
    silence_ends: list[float],
    duration_sec: float,
    pad_sec: float,
) -> list[tuple[float, float]]:
    """Build segments to keep from precomputed silence lists. Silences with duration <= 2*pad_sec are skipped."""
    silence_starts = [normalize_timestamp(x) for x in silence_starts]
    silence_ends = [normalize_timestamp(x) for x in silence_ends]
    duration_sec = normalize_timestamp(duration_sec)
    pad_sec = normalize_timestamp(max(0.0, pad_sec))
    if len(silence_starts) > len(silence_ends):
        silence_ends = list(silence_ends) + [duration_sec]
    segments_to_keep: list[tuple[float, float]] = []
    prev_end = 0.0
    for silence_start, silence_end in zip(silence_starts, silence_ends):
        if silence_end - silence_start <= pad_sec * 2 + TRIM_TIMESTAMP_EPSILON_SEC:
            continue
        if silence_start > prev_end + TRIM_TIMESTAMP_EPSILON_SEC:
            segments_to_keep.append((normalize_timestamp(prev_end), normalize_timestamp(silence_start)))
        prev_end = normalize_timestamp(max(0.0, silence_end - pad_sec))
    if prev_end < duration_sec - TRIM_TIMESTAMP_EPSILON_SEC:
        segments_to_keep.append((normalize_timestamp(prev_end), normalize_timestamp(duration_sec)))
    return segments_to_keep


def _resolve_trim_plan(
    input_file: Path,
    duration_sec: float,
    target_length: Optional[float],
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
) -> tuple[list[float], list[float], float, float, float]:
    """Resolve effective trimming parameters and detected silences."""
    if target_length is None:
        silence_starts, silence_ends = detect_silence_points(input_file, noise_threshold, min_duration)
        leading_edge, trailing_edge = detect_leading_trailing_edge_silence(input_file, duration_sec)
        silence_starts, silence_ends = replace_edge_intervals(
            silence_starts,
            silence_ends,
            leading_edge,
            trailing_edge,
            duration_sec,
        )
        silence_starts, silence_ends = trim_edge_silence(silence_starts, silence_ends, duration_sec)
        return silence_starts, silence_ends, noise_threshold, min_duration, pad_sec

    silence_starts, silence_ends, chosen_threshold, chosen_pad = choose_threshold_and_padding_for_target(
        input_file,
        duration_sec,
        target_length,
        min_duration=TARGET_MIN_DURATION_SEC,
    )
    return silence_starts, silence_ends, chosen_threshold, TARGET_MIN_DURATION_SEC, chosen_pad


def _build_segments_to_keep(
    input_file: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
) -> tuple[list[tuple[float, float]], float, float, float, float]:
    """Build segments_to_keep list using same algorithm as full trim.

    Returns:
        (segments_to_keep, duration_sec, resolved_noise_threshold, resolved_min_duration, resolved_pad_sec)
    """
    duration_sec = probe_duration(input_file)
    if duration_sec <= 0:
        raise ValueError(f"Invalid video duration: {duration_sec}s. Video file may be corrupted or empty.")
    duration_sec = normalize_timestamp(duration_sec)

    if target_length is not None and target_length >= duration_sec - TRIM_TIMESTAMP_EPSILON_SEC:
        # Target length is already satisfied by source duration.
        return ([(0.0, normalize_timestamp(duration_sec))], duration_sec, noise_threshold, min_duration, 0.0)

    silence_starts, silence_ends, chosen_threshold, chosen_min_duration, pad_sec = _resolve_trim_plan(
        input_file,
        duration_sec,
        target_length,
        noise_threshold,
        min_duration,
        pad_sec,
    )

    if len(silence_starts) > len(silence_ends):
        silence_ends = list(silence_ends) + [duration_sec]

    if target_length is not None:
        print(f"Target mode: chosen noise_threshold={chosen_threshold}dB, min_duration={chosen_min_duration}s, pad={pad_sec}s")

    segments_to_keep = _build_segments_from_silences(silence_starts, silence_ends, duration_sec, pad_sec)
    return (segments_to_keep, duration_sec, chosen_threshold, chosen_min_duration, pad_sec)


def create_silence_removed_snippet(
    input_file: Path,
    output_audio_path: Path,
    temp_dir: Path,
    pad_sec: float,
    max_duration: Optional[float] = SNIPPET_MAX_DURATION_SEC,
) -> Path:
    """Create the fixed-parameter transcription snippet.

    Snippet creation always uses a single conservative detection sweep:
    SNIPPET_NOISE_THRESHOLD_DB (-55dB) and SNIPPET_MIN_DURATION_SEC (0.01s), plus standard edge handling.
    """
    return create_silence_removed_audio(
        input_file=input_file,
        output_audio_path=output_audio_path,
        temp_dir=temp_dir,
        noise_threshold=SNIPPET_NOISE_THRESHOLD_DB,
        min_duration=SNIPPET_MIN_DURATION_SEC,
        pad_sec=pad_sec,
        target_length=None,
        max_duration=max_duration,
    )


def create_silence_removed_audio(
    input_file: Path,
    output_audio_path: Path,
    temp_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float] = None,
    max_duration: Optional[float] = None,
) -> Path:
    """Create silence-removed audio (same algorithm as video trim), audio only (-vn).
    If max_duration is set (e.g. 300), limit output to that many seconds (e.g. first 5 min)."""
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)

    # OGG/Opus for smaller payload when path is .ogg; else WAV
    is_ogg = output_audio_path.suffix.lower() == ".ogg"
    if is_ogg:
        acodec = ["-c:a", "libopus", "-ar", "16000", "-ac", "1", "-b:a", "32k"]
    else:
        acodec = ["-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1"]

    segments_to_keep, _, _, _, _ = _build_segments_to_keep(
        input_file, noise_threshold, min_duration, pad_sec, target_length
    )

    if len(segments_to_keep) == 0:
        print("Warning: All audio detected as silence. Creating minimal audio.")
        cmd = build_minimal_audio_command(
            input_file=input_file,
            output_audio=output_audio_path,
            codec_args=acodec,
        )
        print_ffmpeg_cmd(cmd)
        run(cmd, check=True)
        wait_for_file_release(output_audio_path)
        return output_audio_path.resolve()

    # Audio-only filter: atrim each segment, then concat
    filter_complex = build_audio_concat_filter_graph(segments_to_keep)

    scripts_dir = temp_dir / SCRIPTS_DIR
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script_name = f"{output_audio_path.stem}_{int(time.time())}.ffscript"
    filter_script_path = scripts_dir / script_name
    write_filter_graph_script(filter_script_path, filter_complex)
    print(f"[DEBUG] filter_graph_script path: {filter_script_path}")
    print(f"[DEBUG] filter_graph_script exists: {filter_script_path.exists()}")
    cmd = build_silence_removed_audio_command(
        input_file=input_file,
        output_audio_path=output_audio_path,
        filter_script_path=filter_script_path,
        acodec=acodec,
        max_duration=max_duration,
    )
    print_ffmpeg_cmd(cmd)
    run(cmd, check=True)
    print(f"[DEBUG] ffmpeg completed, script still at: {filter_script_path}")
    wait_for_file_release(output_audio_path)
    print(f"Silence-removed audio -> {output_audio_path}")
    return output_audio_path.resolve()


def trim_single_video(
    input_file: Path,
    output_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
    output_basename: Optional[str] = None,
    encoder: VideoEncoderProfile | None = None,
) -> Path:
    """Trim a single video and return the output file path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = output_basename if output_basename is not None else input_file.stem
    output_file = (output_dir / f"{basename}.mp4").resolve()

    if target_length is not None:
        duration_sec = probe_duration(input_file)
        if duration_sec <= 0:
            raise ValueError(f"Invalid video duration: {duration_sec}s. Video file may be corrupted or empty.")
        if target_length >= duration_sec:
            print(f"Target length ({target_length}s) >= original duration ({duration_sec:.3f}s), copying original file")
            try:
                import shutil
                shutil.copyfile(input_file, output_file)
                wait_for_file_release(output_file)
                print(f"Done! Output saved to: {output_file}")
                return output_file.resolve()
            except Exception as e:
                print(f"Error copying file: {e}", file=sys.stderr)
                raise

    segments_to_keep, duration_sec, resolved_noise_threshold, resolved_min_duration, resolved_pad_sec = _build_segments_to_keep(
        input_file,
        noise_threshold,
        min_duration,
        pad_sec,
        target_length,
    )
    encoder = encoder or resolve_video_encoder()

    resulting_length = sum(end - start for start, end in segments_to_keep)
    if target_length is not None:
        print(f"Target length: {target_length}s")
        print(f"Expected resulting length: {resulting_length:.3f}s")

    # Handle case where all audio is silence (no segments to keep)
    if len(segments_to_keep) == 0:
        print("Warning: All audio detected as silence. Creating minimal video (first frame only).")
        # Create minimal video with first frame and silence using the resolved encoder profile.
        cmd = build_minimal_video_command(
            input_file=input_file,
            output_file=output_file,
            encoder=encoder,
        )
        print_ffmpeg_cmd(cmd)
        try:
            run(cmd, check=True)
            wait_for_file_release(output_file)
            print(f"Done! Output saved to: {output_file}")
            return output_file.resolve()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"{encoder.codec} failed while creating minimal fallback video") from e

    filter_complex = build_video_audio_concat_filter_graph(segments_to_keep)

    # Write the filter_complex script under temp/scripts/ (inside output_dir),
    # so paths are stable and debuggable rather than using OS-level temp.
    temp_dir = output_dir / "temp"
    scripts_dir = temp_dir / SCRIPTS_DIR
    scripts_dir.mkdir(parents=True, exist_ok=True)
    filter_script_path = scripts_dir / f"{output_file.stem}_{int(time.time())}.ffscript"
    write_filter_graph_script(filter_script_path, filter_complex)
    print(f"[DEBUG] filter_graph_script path: {filter_script_path}")
    print(f"[DEBUG] filter_graph_script exists: {filter_script_path.exists()}")

    print(f"Input: {input_file}")
    print(f"Output: {output_file}")
    print(f"Settings: noise={resolved_noise_threshold}dB, min_duration={resolved_min_duration}s, pad={resolved_pad_sec}s")
    print(f"Filter complex length: {len(filter_complex)} characters")
    print(f"Number of segments: {len(segments_to_keep)}")
    cmd = build_final_trim_command(
        input_file=input_file,
        output_file=output_file,
        filter_script_path=filter_script_path,
        encoder=encoder,
    )
    print_ffmpeg_cmd(cmd)
    emitted_progress = False

    def _on_progress(percent: int) -> None:
        nonlocal emitted_progress
        emitted_progress = True
        print(f"\rProgress: {percent}%", end="", flush=True)

    try:
        # Run ffmpeg and parse -progress output to display percentage
        run_with_progress(
            cmd,
            expected_total_seconds=resulting_length if resulting_length > 0 else duration_sec,
            on_progress=_on_progress,
        )
        if emitted_progress:
            print()
    except subprocess.CalledProcessError:
        print(f"{encoder.codec} encode failed while trimming video", file=sys.stderr)
        raise

    wait_for_file_release(output_file)
    print(f"Done! Output saved to: {output_file}")
    print(f"[DEBUG] ffmpeg completed, script still at: {filter_script_path}")
    return output_file.resolve()

