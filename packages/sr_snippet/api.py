"""Silence-removed audio snippet extraction for transcription."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.core.constants import (
    SNIPPET_MAX_DURATION_SEC,
    SNIPPET_MIN_DURATION_SEC,
    SNIPPET_NOISE_THRESHOLD_DB,
)
from src.ffmpeg.probing import probe_duration
from src.ffmpeg.transcode import (
    build_minimal_audio_command,
    build_silent_audio_file_command,
    build_silence_removed_audio_command,
)
from src.ffmpeg.silence_removed_runner import (
    run_minimal_ffmpeg_output,
    run_silence_removed_media_with_script,
)
from src.ffmpeg.trim_script_bundle import load_trim_script_bundle


def create_silence_removed_snippet(
    input_file: Path,
    output_audio_path: Path,
    temp_dir: Path,
    trim_script_bundle_dir: Path,
    pad_sec: float,
    max_duration: Optional[float] = SNIPPET_MAX_DURATION_SEC,
) -> Path:
    """Create transcription snippet from a pre-generated trim-script bundle."""
    return create_silence_removed_audio(
        input_file=input_file,
        output_audio_path=output_audio_path,
        temp_dir=temp_dir,
        trim_script_bundle_dir=trim_script_bundle_dir,
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
    trim_script_bundle_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float] = None,
    max_duration: Optional[float] = None,
) -> Path:
    """Create silence-removed audio from a pre-generated trim-script bundle."""
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)
    bundle = load_trim_script_bundle(trim_script_bundle_dir)

    is_ogg = output_audio_path.suffix.lower() == ".ogg"
    if is_ogg:
        acodec = ["-c:a", "libopus", "-ar", "16000", "-ac", "1", "-b:a", "32k"]
    else:
        acodec = ["-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1"]

    if bundle.snippet_strategy == "silent":
        duration_sec = probe_duration(input_file)
        if max_duration is not None:
            duration_sec = min(duration_sec, max_duration)
        duration_sec = max(0.1, float(duration_sec))
        return run_minimal_ffmpeg_output(
            output_file=output_audio_path,
            cmd=build_silent_audio_file_command(
                output_audio=output_audio_path,
                duration_sec=duration_sec,
                codec_args=acodec,
            ),
            command_label="Silent audio (no input audio)",
        )

    if bundle.snippet_strategy == "minimal":
        return run_minimal_ffmpeg_output(
            output_file=output_audio_path,
            cmd=build_minimal_audio_command(
                input_file=input_file,
                output_audio=output_audio_path,
                codec_args=acodec,
            ),
            command_label="Audio",
        )

    if bundle.snippet_script_path is None:
        raise RuntimeError(f"Missing snippet filter script in bundle: {trim_script_bundle_dir}")

    return run_silence_removed_media_with_script(
        input_file=input_file,
        output_file=output_audio_path,
        filter_script_path=bundle.snippet_script_path,
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
