"""Video trimming functionality."""

import subprocess
import time
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Literal, Optional

from src.core.constants import (
    SCRIPTS_DIR,
    SNIPPET_MAX_DURATION_SEC,
    SNIPPET_MIN_DURATION_SEC,
    SNIPPET_NOISE_THRESHOLD_DB,
    TITLE_BANNER_HEIGHT_FRACTION,
    TITLE_BANNER_START_FRACTION,
    TITLE_FONT_DEFAULT,
    TRIM_TIMESTAMP_EPSILON_SEC,
    TrimDefaults,
    resolve_trim_defaults,
)
from src.ffmpeg.encoding_resolver import VideoEncoderProfile, resolve_video_encoder
from src.ffmpeg.core import print_ffmpeg_cmd
from src.ffmpeg.filter_graph import (
    build_audio_concat_filter_graph,
    build_video_audio_concat_filter_graph,
    build_video_audio_concat_filter_graph_with_title_overlay,
    build_video_lavfi_audio_concat_filter_graph,
    build_video_lavfi_audio_concat_filter_graph_with_title_overlay,
    write_filter_graph_script,
)
from src.ffmpeg.probing import probe_duration, probe_has_audio_stream, probe_video_dimensions
from src.media.title_overlay import build_title_overlay
from src.ffmpeg.runner import run, run_with_progress
from src.ffmpeg.transcode import (
    build_final_trim_command,
    build_minimal_audio_command,
    build_minimal_video_command,
    build_silent_audio_file_command,
    build_silence_removed_audio_command,
)
from src.core.fs_utils import wait_for_file_release
from src.core.paths import get_font_cache_path, get_title_overlay_path
from src.media.silence_detector import (
    choose_threshold_and_padding_for_target,
    normalize_timestamp,
    build_keep_segments_from_silences,
    prepare_silence_intervals_with_edges,
    truncate_segments_to_max_length,
)

TrimPlanMode = Literal["target", "non_target"]


@dataclass(frozen=True)
class TrimPlan:
    """Resolved trim strategy and segment output for one media run."""

    mode: TrimPlanMode
    segments_to_keep: list[tuple[float, float]]
    input_duration_sec: float
    resulting_length_sec: float
    resolved_noise_threshold: float
    resolved_min_duration: float
    resolved_pad_sec: float
    target_length: Optional[float]
    should_copy_input: bool = False


def should_copy_when_target_exceeds_input(duration_sec: float, target_length: Optional[float]) -> bool:
    """Return True when target mode can skip trimming because input is already short enough."""
    return target_length is not None and target_length >= duration_sec - TRIM_TIMESTAMP_EPSILON_SEC


def _probe_and_validate_duration(input_file: Path) -> float:
    duration_sec = probe_duration(input_file)
    if duration_sec <= 0:
        raise ValueError(f"Invalid video duration: {duration_sec}s. Video file may be corrupted or empty.")
    return normalize_timestamp(duration_sec)


def build_trim_plan(
    input_file: Path,
    target_length: Optional[float],
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
) -> TrimPlan:
    """Resolve mode policy and return a reusable trim plan."""
    trim_defaults = resolve_trim_defaults(
        target_length=target_length,
        noise_threshold=noise_threshold,
        min_duration=min_duration,
        pad_sec=pad_sec,
    )
    duration_sec = _probe_and_validate_duration(input_file)
    if should_copy_when_target_exceeds_input(duration_sec, target_length):
        return TrimPlan(
            mode="target",
            segments_to_keep=[(0.0, normalize_timestamp(duration_sec))],
            input_duration_sec=duration_sec,
            resulting_length_sec=duration_sec,
            resolved_noise_threshold=trim_defaults.noise_threshold,
            resolved_min_duration=trim_defaults.min_duration,
            resolved_pad_sec=0.0,
            target_length=target_length,
            should_copy_input=True,
        )

    if target_length is None:
        return _build_non_target_trim_plan(input_file=input_file, duration_sec=duration_sec, trim_defaults=trim_defaults)

    return _build_target_trim_plan(
        input_file=input_file,
        duration_sec=duration_sec,
        target_length=target_length,
        trim_defaults=trim_defaults,
    )


def _build_non_target_trim_plan(
    input_file: Path,
    duration_sec: float,
    trim_defaults: TrimDefaults,
) -> TrimPlan:
    """Build a non-target trim plan."""
    silence_starts, silence_ends = prepare_silence_intervals_with_edges(
        input_file=input_file,
        duration_sec=duration_sec,
        noise_threshold=trim_defaults.noise_threshold,
        min_duration=trim_defaults.min_duration,
    )
    segments_to_keep = build_keep_segments_from_silences(
        silence_starts=silence_starts,
        silence_ends=silence_ends,
        duration_sec=duration_sec,
        pad_sec=trim_defaults.pad_sec,
    )
    resulting_length = normalize_timestamp(sum(end - start for start, end in segments_to_keep))
    return TrimPlan(
        mode="non_target",
        segments_to_keep=segments_to_keep,
        input_duration_sec=duration_sec,
        resulting_length_sec=resulting_length,
        resolved_noise_threshold=trim_defaults.noise_threshold,
        resolved_min_duration=trim_defaults.min_duration,
        resolved_pad_sec=trim_defaults.pad_sec,
        target_length=None,
    )


def _build_target_trim_plan(
    input_file: Path,
    duration_sec: float,
    target_length: float,
    trim_defaults: TrimDefaults,
) -> TrimPlan:
    """Build a target-mode trim plan with adaptive threshold/padding policy."""
    silence_starts, silence_ends, chosen_threshold, chosen_pad = choose_threshold_and_padding_for_target(
        input_file=input_file,
        duration_sec=duration_sec,
        target_length=target_length,
        min_duration=trim_defaults.min_duration,
        override_noise_threshold=trim_defaults.noise_threshold,
    )
    segments_to_keep = build_keep_segments_from_silences(
        silence_starts=silence_starts,
        silence_ends=silence_ends,
        duration_sec=duration_sec,
        pad_sec=chosen_pad,
    )
    resulting_length = normalize_timestamp(sum(end - start for start, end in segments_to_keep))

    if resulting_length > target_length + TRIM_TIMESTAMP_EPSILON_SEC:
        segments_to_keep = truncate_segments_to_max_length(segments_to_keep, target_length)
        resulting_length = normalize_timestamp(sum(end - start for start, end in segments_to_keep))

    print(
        f"Target mode: chosen noise_threshold={chosen_threshold}dB, "
        f"min_duration={trim_defaults.min_duration}s, pad={chosen_pad}s"
    )
    return TrimPlan(
        mode="target",
        segments_to_keep=segments_to_keep,
        input_duration_sec=duration_sec,
        resulting_length_sec=resulting_length,
        resolved_noise_threshold=chosen_threshold,
        resolved_min_duration=trim_defaults.min_duration,
        resolved_pad_sec=chosen_pad,
        target_length=target_length,
    )


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
    plan = build_trim_plan(
        input_file,
        target_length,
        noise_threshold,
        min_duration,
        pad_sec,
    )
    return (
        plan.segments_to_keep,
        plan.input_duration_sec,
        plan.resolved_noise_threshold,
        plan.resolved_min_duration,
        plan.resolved_pad_sec,
    )


def _copy_input_video(input_file: Path, output_file: Path) -> Path:
    print(
        f"Target length >= original duration, copying original file "
        f"{input_file} -> {output_file}"
    )
    try:
        shutil.copyfile(input_file, output_file)
        return output_file.resolve()
    except Exception as exc:
        raise RuntimeError(f"Failed to copy original file from {input_file} to {output_file}") from exc


def _run_minimal_output(
    *,
    output_file: Path,
    cmd: list[str],
    command_label: str,
) -> Path:
    print_ffmpeg_cmd(cmd)
    try:
        run(cmd, check=True)
        wait_for_file_release(output_file)
        return output_file.resolve()
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"{command_label} failed while creating minimal output") from exc


def _run_silence_removed_media(
    *,
    input_file: Path,
    output_file: Path,
    temp_dir: Path,
    segments_to_keep: list[tuple[float, float]],
    build_filter_graph: Callable[[list[tuple[float, float]], int | None], str],
    build_command: Callable[[Path, Path, Path], list[str]],
    expected_total_seconds: Optional[float] = None,
    on_progress: Optional[Callable[[int], None]] = None,
    command_label: Optional[str] = None,
    overlay_y: int | None = None,
) -> Path:
    filter_complex = build_filter_graph(segments_to_keep, overlay_y)

    scripts_dir = temp_dir / SCRIPTS_DIR
    scripts_dir.mkdir(parents=True, exist_ok=True)
    filter_script_path = scripts_dir / f"{output_file.stem}_{int(time.time())}.ffscript"
    write_filter_graph_script(filter_script_path, filter_complex)

    cmd = build_command(input_file, output_file, filter_script_path)
    print_ffmpeg_cmd(cmd)
    if expected_total_seconds is not None:
        emitted_progress = False

        def _on_progress(percent: int) -> None:
            nonlocal emitted_progress
            emitted_progress = True
            if on_progress is not None:
                on_progress(percent)
        try:
            run_with_progress(
                cmd,
                expected_total_seconds=expected_total_seconds,
                on_progress=_on_progress,
            )
        except subprocess.CalledProcessError as exc:
            if command_label is None:
                raise
            raise RuntimeError(f"{command_label} failed") from exc
        if emitted_progress:
            print()
    else:
        try:
            run(cmd, check=True)
        except subprocess.CalledProcessError as exc:
            if command_label is not None:
                raise RuntimeError(f"{command_label} failed") from exc
            raise

    wait_for_file_release(output_file)
    print(f"Done! Output saved to: {output_file}")
    return output_file.resolve()


def create_silence_removed_snippet(
    input_file: Path,
    output_audio_path: Path,
    temp_dir: Path,
    pad_sec: float,
    max_duration: Optional[float] = SNIPPET_MAX_DURATION_SEC,
) -> Path:
    """Create the fixed-parameter transcription snippet.

    Snippet creation uses `prepare_silence_intervals_with_edges` through the shared trim
    path in `_build_segments_to_keep` to keep edge handling aligned with final output.
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
    If max_duration is set (e.g. 180), limit output to that many seconds (e.g. first 3 min)."""
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)

    # OGG/Opus for smaller payload when path is .ogg; else WAV
    is_ogg = output_audio_path.suffix.lower() == ".ogg"
    if is_ogg:
        acodec = ["-c:a", "libopus", "-ar", "16000", "-ac", "1", "-b:a", "32k"]
    else:
        acodec = ["-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1"]

    if not probe_has_audio_stream(input_file):
        duration_sec = probe_duration(input_file)
        if max_duration is not None:
            duration_sec = min(duration_sec, max_duration)
        duration_sec = max(0.1, float(duration_sec))
        print("Warning: Input has no audio stream; writing silent audio for transcription/snippet.")
        return _run_minimal_output(
            output_file=output_audio_path,
            cmd=build_silent_audio_file_command(
                output_audio=output_audio_path,
                duration_sec=duration_sec,
                codec_args=acodec,
            ),
            command_label="Silent audio (no input audio)",
        )

    segments_to_keep, _, _, _, _ = _build_segments_to_keep(
        input_file, noise_threshold, min_duration, pad_sec, target_length
    )

    if len(segments_to_keep) == 0:
        print("Warning: All audio detected as silence. Creating minimal audio.")
        if not probe_has_audio_stream(input_file):
            duration_sec = max(0.1, float(probe_duration(input_file)))
            if max_duration is not None:
                duration_sec = min(duration_sec, max_duration)
            return _run_minimal_output(
                output_file=output_audio_path,
                cmd=build_silent_audio_file_command(
                    output_audio=output_audio_path,
                    duration_sec=duration_sec,
                    codec_args=acodec,
                ),
                command_label="Silent audio (no input audio)",
            )
        return _run_minimal_output(
            output_file=output_audio_path,
            cmd=build_minimal_audio_command(
                input_file=input_file,
                output_audio=output_audio_path,
                codec_args=acodec,
            ),
            command_label="Audio",
        )

    return _run_silence_removed_media(
        input_file=input_file,
        output_file=output_audio_path,
        temp_dir=temp_dir,
        segments_to_keep=segments_to_keep,
        build_filter_graph=build_audio_concat_filter_graph,
        build_command=lambda in_file, out_file, filter_script_path: build_silence_removed_audio_command(
            input_file=in_file,
            output_audio_path=out_file,
            filter_script_path=filter_script_path,
            acodec=acodec,
            max_duration=max_duration,
        ),
        command_label="Silence-removed audio",
    )


def trim_single_video(
    input_file: Path,
    output_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
    output_basename: Optional[str] = None,
    encoder: VideoEncoderProfile | None = None,
    title_path: Path | None = None,
    title_font: str | None = None,
) -> Path:
    """Trim a single video and return the output file path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = output_basename if output_basename is not None else input_file.stem
    output_file = (output_dir / f"{basename}.mp4").resolve()

    plan = build_trim_plan(
        input_file=input_file,
        target_length=target_length,
        noise_threshold=noise_threshold,
        min_duration=min_duration,
        pad_sec=pad_sec,
    )

    if plan.should_copy_input and title_path is None:
        copied_output_file = _copy_input_video(input_file=input_file, output_file=output_file)
        wait_for_file_release(copied_output_file)
        return copied_output_file

    segments_to_keep = plan.segments_to_keep
    duration_sec = plan.input_duration_sec
    resolved_noise_threshold = plan.resolved_noise_threshold
    resolved_min_duration = plan.resolved_min_duration
    resolved_pad_sec = plan.resolved_pad_sec
    encoder = encoder or resolve_video_encoder()
    resulting_length = plan.resulting_length_sec
    input_has_audio = probe_has_audio_stream(input_file)
    print(f"Input: {input_file}")
    print(f"Output: {output_file}")
    print(f"Settings: noise={resolved_noise_threshold}dB, min_duration={resolved_min_duration}s, pad={resolved_pad_sec}s")
    print(f"Number of segments: {len(segments_to_keep)}")

    if target_length is not None:
        print(f"Target length: {target_length}s")
        print(f"Expected resulting length: {resulting_length:.3f}s")

    # Handle case where all audio is silence (no segments to keep)
    font_name = title_font or TITLE_FONT_DEFAULT
    temp_dir = output_dir / "temp"
    title_overlay_path: Path | None = None
    banner_top: int | None = None
    if title_path is not None:
        title_text = title_path.read_text(encoding="utf-8").strip()
        if not title_text:
            raise RuntimeError(f"Empty title at {title_path}")
        video_width, video_height = probe_video_dimensions(input_file)
        banner_height = max(1, int(video_height * TITLE_BANNER_HEIGHT_FRACTION))
        banner_top = int(video_height * TITLE_BANNER_START_FRACTION)
        title_overlay_path = build_title_overlay(
            title=title_text,
            video_width=video_width,
            banner_height=banner_height,
            output_file=get_title_overlay_path(temp_dir, basename),
            font_family=font_name,
            font_cache_dir=get_font_cache_path(temp_dir),
        )

    # Handle case where all audio is silence (no segments to keep)
    if len(segments_to_keep) == 0:
        print("Warning: All audio detected as silence. Creating minimal video (first frame only).")
        # Create minimal video with first frame and silence using the resolved encoder profile.
        return _run_minimal_output(
            output_file=output_file,
            cmd=build_minimal_video_command(
                input_file=input_file,
                output_file=output_file,
                encoder=encoder,
                title_overlay_path=title_overlay_path,
                title_overlay_y=banner_top,
            ),
            command_label=f"{encoder.codec} encode",
        )

    if title_overlay_path is not None:
        filter_builder = (
            build_video_audio_concat_filter_graph_with_title_overlay
            if input_has_audio
            else build_video_lavfi_audio_concat_filter_graph_with_title_overlay
        )
        use_lavfi_silent_audio = not input_has_audio
    else:
        filter_builder = (
            build_video_audio_concat_filter_graph
            if input_has_audio
            else build_video_lavfi_audio_concat_filter_graph
        )
        use_lavfi_silent_audio = not input_has_audio
    return _run_silence_removed_media(
        input_file=input_file,
        output_file=output_file,
        temp_dir=output_dir / "temp",
        segments_to_keep=segments_to_keep,
        build_filter_graph=filter_builder,
        build_command=lambda in_file, out_file, filter_script: build_final_trim_command(
            input_file=in_file,
            output_file=out_file,
            filter_script_path=filter_script,
            encoder=encoder,
            title_overlay_path=title_overlay_path,
            title_overlay_y=banner_top,
            extra_silent_audio_lavfi=use_lavfi_silent_audio,
        ),
        expected_total_seconds=resulting_length if resulting_length > 0 else duration_sec,
        on_progress=lambda percent: print(f"\rProgress: {percent}%", end="", flush=True),
        command_label=f"{encoder.codec} encode",
        overlay_y=banner_top,
    )

