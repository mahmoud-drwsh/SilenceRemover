"""Three-phase pipeline orchestration for SilenceRemover."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Optional

from src.core.cli import parse_args
from src.core.constants import (
    COMPLETED_DIR,
    SNIPPET_MAX_DURATION_SEC,
)
from src.core.paths import (
    get_snippet_path,
    get_title_path,
    get_transcript_path,
    is_completed,
    is_title_done,
    is_transcript_done,
    mark_completed,
    resolve_output_basename,
)
from src.startup import build_startup_context
from src.llm.title import generate_title_from_transcript
from src.llm.transcription import get_audio_path_for_media, transcribe_and_save
from src.ffmpeg.encoding_resolver import VideoEncoderProfile
from src.media.trim import create_silence_removed_snippet, trim_single_video


def transcribe_media(media_path: Path, temp_dir: Path, api_key: str, basename: str) -> None:
    """Transcribe from a video or audio file and save transcript to file."""
    audio_path = get_audio_path_for_media(media_path, temp_dir, basename)
    transcript_path = get_transcript_path(temp_dir, basename)

    print("Transcribing with OpenRouter...")
    transcribe_and_save(
        api_key=api_key,
        audio_path=audio_path,
        output_path=transcript_path,
        log_dir=temp_dir,
    )


def generate_title(temp_dir: Path, api_key: str, basename: str) -> None:
    """Generate title from transcript file and save to file."""
    transcript_path = get_transcript_path(temp_dir, basename)
    title_path = get_title_path(temp_dir, basename)

    print("Generating YouTube title...")
    generate_title_from_transcript(
        api_key=api_key,
        transcript_path=transcript_path,
        output_path=title_path,
        log_dir=temp_dir,
    )


def transcribe_single_video(media_path: Path, temp_dir: Path, api_key: str, basename: str) -> tuple[str, str]:
    """Transcribe from a video or audio file. Returns (transcript_text, title_text)."""
    transcribe_media(media_path, temp_dir, api_key, basename)
    generate_title(temp_dir, api_key, basename)

    transcript_path = get_transcript_path(temp_dir, basename)
    title_path = get_title_path(temp_dir, basename)

    transcript_text = transcript_path.read_text(encoding="utf-8").strip()
    title_text = title_path.read_text(encoding="utf-8").strip()

    return transcript_text, title_text


def run_transcription_phase(
    video_path: Path,
    temp_dir: Path,
    pad_sec: float,
    api_key: str,
) -> bool:
    """Phase 1: Create snippet and transcribe it to `temp/transcript/{basename}.txt`."""
    basename = video_path.stem
    snippet_path = get_snippet_path(temp_dir, basename)

    if is_transcript_done(temp_dir, basename):
        print(f"Phase 1 already done for {video_path.name}, skipping transcription.")
        return True

    try:
        print(f"\n[1/3] Creating snippet (first 5 min, silence-removed): {video_path.name}")
        create_silence_removed_snippet(
            input_file=video_path,
            output_audio_path=snippet_path,
            temp_dir=temp_dir,
            pad_sec=pad_sec,
            max_duration=SNIPPET_MAX_DURATION_SEC,
        )

        print(f"\n[1/3] Transcribing: {snippet_path.name}")
        transcribe_media(media_path=snippet_path, temp_dir=temp_dir, api_key=api_key, basename=basename)

        print(f"\n✓ Phase 1 (transcription) done: {video_path.name}")
        return True
    except Exception as e:
        print(f"\n✗ Phase 1 error for {video_path.name}: {e}", file=sys.stderr)
        traceback.print_exc()
        return False


def run_title_phase(video_path: Path, temp_dir: Path, api_key: str) -> bool:
    """Phase 2: Generate title from transcript to `temp/title/{basename}.txt`."""
    basename = video_path.stem

    if not is_transcript_done(temp_dir, basename):
        print(f"No transcript for {video_path.name}, skipping title phase.")
        return False

    if is_title_done(temp_dir, basename):
        print(f"Phase 2 already done for {video_path.name}, skipping title generation.")
        return True

    try:
        print(f"\n[2/3] Generating title for: {video_path.name}")
        generate_title(temp_dir=temp_dir, api_key=api_key, basename=basename)

        print(f"\n✓ Phase 2 (title generation) done: {video_path.name}")
        return True
    except Exception as e:
        print(f"\n✗ Phase 2 error for {video_path.name}: {e}", file=sys.stderr)
        traceback.print_exc()
        return False


def run_output_phase(
    video_path: Path,
    output_dir: Path,
    temp_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
    encoder: VideoEncoderProfile | None = None,
) -> bool:
    """Phase 3: Full video trim with title-based output filename."""
    basename = video_path.stem

    if is_completed(temp_dir, basename):
        print(f"Phase 3 already done for {video_path.name}, skipping.")
        return True

    if not is_title_done(temp_dir, basename):
        print(f"No title for {video_path.name}, skipping output phase.")
        return False

    try:
        title = get_title_path(temp_dir, basename).read_text(encoding="utf-8").strip()
        if not title:
            print(f"Empty title for {video_path.name}, skipping output phase.")
            return False

        chosen_basename = resolve_output_basename(title, output_dir)
        print(f"\n[3/3] Creating final output: {video_path.name} -> {chosen_basename}.mp4")
        trim_single_video(
            input_file=video_path,
            output_dir=output_dir,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
            target_length=target_length,
            output_basename=chosen_basename,
            encoder=encoder,
        )
        mark_completed(temp_dir, basename)
        print(f"\n✓ Phase 3 (output) done: {video_path.name}")
        return True
    except Exception as e:
        print(f"\n✗ Phase 3 error for {video_path.name}: {e}", file=sys.stderr)
        traceback.print_exc()
        return False


def run() -> None:
    """Run the full three-phase media processing pipeline."""
    args = parse_args()
    startup = build_startup_context(args)
    selected_encoder = startup.encoder
    api_key = startup.api_key
    temp_dir = startup.temp_dir
    videos = startup.videos

    print(f"Resolved encoder: {selected_encoder.name} ({selected_encoder.codec})")

    print(f"Found {len(startup.videos)} video file(s)")
    print(f"Input: {startup.input_dir}")
    print(f"Output: {startup.output_dir}")
    print(f"Temp: {startup.temp_dir}")
    print("-" * 60)

    for i, video_file in enumerate(startup.videos, 1):
        print(f"\n{'='*60}")
        print(f"[1/3][{i}/{len(videos)}] Transcription: {video_file.name}")
        print(f"{'='*60}")
        run_transcription_phase(
            video_path=video_file,
            temp_dir=temp_dir,
            pad_sec=startup.pad_sec,
            api_key=api_key,
        )

    for i, video_file in enumerate(videos, 1):
        print(f"\n{'='*60}")
        print(f"[2/3][{i}/{len(videos)}] Title Generation: {video_file.name}")
        print(f"{'='*60}")
        run_title_phase(
            video_path=video_file,
            temp_dir=temp_dir,
            api_key=api_key,
        )

    for i, video_file in enumerate(videos, 1):
        print(f"\n{'='*60}")
        print(f"[3/3][{i}/{len(videos)}] Final Output: {video_file.name}")
        print(f"{'='*60}")
        run_output_phase(
            video_path=video_file,
            output_dir=startup.output_dir,
            temp_dir=startup.temp_dir,
            noise_threshold=startup.noise_threshold,
            min_duration=startup.min_duration,
            pad_sec=startup.pad_sec,
            target_length=startup.target_length,
            encoder=startup.encoder,
        )

    completed_dir = startup.temp_dir / COMPLETED_DIR
    completed = sum(1 for p in completed_dir.iterdir() if p.is_file())
    print(f"\n{'='*60}")
    print("Processing complete!")
    print(f"Completed: {completed}/{len(videos)}")
    print(f"{'='*60}")
