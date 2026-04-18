"""Silence-removed audio snippet extraction for transcription."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.core.constants import (
    SNIPPET_MAX_DURATION_SEC,
    SNIPPET_MIN_DURATION_SEC,
    SNIPPET_NOISE_THRESHOLD_DB,
)
from src.ffmpeg.transcode import (
    build_silence_removed_audio_command,
)
from src.ffmpeg.silence_removed_runner import (
    run_silence_removed_media_with_script,
)
from src.ffmpeg.trim_script_bundle import load_trim_script


def create_silence_removed_snippet(
    input_file: Path,
    output_audio_path: Path,
    temp_dir: Path,
    trim_script_path: Path,
    pad_sec: float,
    max_duration: Optional[float] = SNIPPET_MAX_DURATION_SEC,
) -> Path:
    """Create transcription snippet from a pre-generated trim script."""
    return create_silence_removed_audio(
        input_file=input_file,
        output_audio_path=output_audio_path,
        temp_dir=temp_dir,
        trim_script_path=trim_script_path,
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
    trim_script_path: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float] = None,
    max_duration: Optional[float] = None,
) -> Path:
    """Create silence-removed audio from a pre-generated trim script."""
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = load_trim_script(trim_script_path)

    is_ogg = output_audio_path.suffix.lower() == ".ogg"
    if is_ogg:
        acodec = ["-c:a", "libopus", "-ar", "16000", "-ac", "1", "-b:a", "32k"]
    else:
        acodec = ["-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1"]

    return run_silence_removed_media_with_script(
        input_file=input_file,
        output_file=output_audio_path,
        filter_script_path=artifact.script_path,
        build_command=lambda in_file, out_file, filter_script_path: build_silence_removed_audio_command(
            input_file=in_file,
            output_audio_path=out_file,
            filter_script_path=filter_script_path,
            acodec=acodec,
            has_video_output="[outv]" in artifact.filter_graph,
            max_duration=max_duration,
        ),
        command_label="Silence-removed audio",
    )


__all__ = [
    "create_silence_removed_audio",
    "create_silence_removed_snippet",
]
