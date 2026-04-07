"""Silence-removed audio snippet extraction for transcription."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.core.constants import (
    SNIPPET_MAX_DURATION_SEC,
    SNIPPET_MIN_DURATION_SEC,
    SNIPPET_NOISE_THRESHOLD_DB,
)
from sr_filter_graph import build_audio_concat_filter_graph
from src.ffmpeg.probing import probe_duration, probe_has_audio_stream
from src.ffmpeg.transcode import (
    build_minimal_audio_command,
    build_silent_audio_file_command,
    build_silence_removed_audio_command,
)
from src.ffmpeg.silence_removed_runner import (
    run_minimal_ffmpeg_output,
    run_silence_removed_media,
)
from sr_trim_plan import build_trim_plan


def _segments_from_trim_plan(
    input_file: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
    temp_dir: Optional[Path] = None,
) -> tuple[list[tuple[float, float]], float, float, float, float]:
    plan = build_trim_plan(
        input_file,
        target_length,
        noise_threshold,
        min_duration,
        pad_sec,
        temp_dir,
    )
    return (
        plan.segments_to_keep,
        plan.input_duration_sec,
        plan.resolved_noise_threshold,
        plan.resolved_min_duration,
        plan.resolved_pad_sec,
    )


def create_silence_removed_snippet(
    input_file: Path,
    output_audio_path: Path,
    temp_dir: Path,
    pad_sec: float,
    max_duration: Optional[float] = SNIPPET_MAX_DURATION_SEC,
) -> Path:
    """Create the fixed-parameter transcription snippet.

    Uses the shared trim plan (non-target path with snippet constants) so edge
    handling matches final output.
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
    If max_duration is set (e.g. 180), limit output to that many seconds."""
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)

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
        return run_minimal_ffmpeg_output(
            output_file=output_audio_path,
            cmd=build_silent_audio_file_command(
                output_audio=output_audio_path,
                duration_sec=duration_sec,
                codec_args=acodec,
            ),
            command_label="Silent audio (no input audio)",
        )

    segments_to_keep, _, _, _, _ = _segments_from_trim_plan(
        input_file, noise_threshold, min_duration, pad_sec, target_length, temp_dir
    )

    if len(segments_to_keep) == 0:
        print("Warning: All audio detected as silence. Creating minimal audio.")
        if not probe_has_audio_stream(input_file):
            duration_sec = max(0.1, float(probe_duration(input_file)))
            if max_duration is not None:
                duration_sec = min(duration_sec, max_duration)
            return run_minimal_ffmpeg_output(
                output_file=output_audio_path,
                cmd=build_silent_audio_file_command(
                    output_audio=output_audio_path,
                    duration_sec=duration_sec,
                    codec_args=acodec,
                ),
                command_label="Silent audio (no input audio)",
            )
        return run_minimal_ffmpeg_output(
            output_file=output_audio_path,
            cmd=build_minimal_audio_command(
                input_file=input_file,
                output_audio=output_audio_path,
                codec_args=acodec,
            ),
            command_label="Audio",
        )

    return run_silence_removed_media(
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


__all__ = [
    "create_silence_removed_audio",
    "create_silence_removed_snippet",
]
