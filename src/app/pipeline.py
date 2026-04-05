"""Three-phase pipeline orchestration for SilenceRemover."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.core.cli import parse_args
from src.core.constants import (
    AUDIO_EXTENSIONS,
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
from src.startup import StartupContext, build_startup_context
from src.ffmpeg.encoding_resolver import VideoEncoderProfile
from sr_snippet import create_silence_removed_snippet
from sr_telegram_notify import notify_final_output_ready
from sr_title import generate_title_from_transcript
from sr_transcription import transcribe_and_save
from src.media.trim import trim_single_video

# Optional MP3 Manager integration for title sync and upload
try:
    from sr_mp3_manager import Mp3ApiClient, sync_titles, get_uploaded_file_ids, check_uploaded
    _MP3_AVAILABLE = True
except ImportError:
    _MP3_AVAILABLE = False

QUICK_TEST_OUTPUT_SECONDS = 5.0


@dataclass(frozen=True)
class _PipelinePhase:
    index: int
    label: str
    run: Callable[[Path, int, int], bool]


def _run_phase(videos: list[Path], phase: _PipelinePhase, total_phases: int) -> None:
    """Run one phase over all videos with shared progress output."""
    n = len(videos)
    for i, video_file in enumerate(videos, 1):
        print(f"\n{'='*60}")
        print(f"[{phase.index}/{total_phases}][{i}/{n}] {phase.label}: {video_file.name}")
        print(f"{'='*60}")
        phase.run(video_file, i, n)


def _run_phase_step(
    *,
    video_path: Path,
    already_done: bool,
    already_done_message: str,
    work_fn: Callable[[], None],
    success_message: str,
    failure_label: str,
    precondition_ok: bool = True,
    precondition_message: str | None = None,
) -> bool:
    """Centralized phase execution wrapper with consistent skip/error behavior."""
    if already_done:
        print(already_done_message)
        return True

    if not precondition_ok:
        if precondition_message is not None:
            print(precondition_message)
        return False

    try:
        work_fn()
        print(success_message)
        return True
    except ValueError as e:
        if "Invalid video duration" in str(e):
            print(f"⚠ Skipping invalid video: {video_path.name}")
            return False
        raise
    except Exception as e:
        print(f"\n✗ {failure_label} error for {video_path.name}: {e}", file=sys.stderr)
        traceback.print_exc()
        return False


def transcribe_media(audio_path: Path, temp_dir: Path, api_key: str, basename: str) -> None:
    """Transcribe from an audio file and save transcript to file.

    ``audio_path`` must be a supported audio extension (see ``AUDIO_EXTENSIONS``);
    video inputs are not accepted here—produce a snippet or extract audio first.
    """
    ext = audio_path.suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(AUDIO_EXTENSIONS))
        raise ValueError(
            f"transcribe_media requires an audio file; got suffix {ext!r} for {audio_path.name}. "
            f"Allowed extensions: {allowed}"
        )
    resolved = audio_path.resolve()
    transcript_path = get_transcript_path(temp_dir, basename)

    print("Transcribing with OpenRouter...")
    transcribe_and_save(
        api_key=api_key,
        audio_path=resolved,
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


def run_transcription_phase(
    video_path: Path,
    temp_dir: Path,
    pad_sec: float,
    api_key: str,
    *,
    total_phases: int = 4,
) -> bool:
    """Phase 1: Create snippet and transcribe it to `temp/transcript/{basename}.txt`."""
    basename = video_path.stem
    snippet_path = get_snippet_path(temp_dir, basename)

    def _perform() -> None:
        print(
            f"\n[1/{total_phases}] Creating snippet (first 3 min, silence-removed): {video_path.name}"
        )
        create_silence_removed_snippet(
            input_file=video_path,
            output_audio_path=snippet_path,
            temp_dir=temp_dir,
            pad_sec=pad_sec,
            max_duration=SNIPPET_MAX_DURATION_SEC,
        )

        print(f"\n[1/{total_phases}] Transcribing: {snippet_path.name}")
        transcribe_media(audio_path=snippet_path, temp_dir=temp_dir, api_key=api_key, basename=basename)

    return _run_phase_step(
        video_path=video_path,
        already_done=is_transcript_done(temp_dir, basename),
        already_done_message=f"Phase 1 already done for {video_path.name}, skipping transcription.",
        work_fn=_perform,
        success_message=f"\n✓ Phase 1 (transcription) done: {video_path.name}",
        failure_label="Phase 1",
    )


def run_title_phase(
    video_path: Path,
    temp_dir: Path,
    api_key: str,
    *,
    total_phases: int = 4,
) -> bool:
    """Phase 2: Generate title from transcript to `temp/title/{basename}.txt`."""
    basename = video_path.stem

    def _perform() -> None:
        print(f"\n[2/{total_phases}] Generating title for: {video_path.name}")
        generate_title(temp_dir=temp_dir, api_key=api_key, basename=basename)

    return _run_phase_step(
        video_path=video_path,
        already_done=is_title_done(temp_dir, basename),
        already_done_message=f"Phase 2 already done for {video_path.name}, skipping title generation.",
        precondition_ok=is_transcript_done(temp_dir, basename),
        precondition_message=f"No transcript for {video_path.name}; cannot run title generation.",
        work_fn=_perform,
        success_message=f"\n✓ Phase 2 (title generation) done: {video_path.name}",
        failure_label="Phase 2",
    )


def run_mp3_upload_phase(
    video_path: Path,
    temp_dir: Path,
    uploaded_ids: list[str],
    *,
    total_phases: int = 4,
) -> bool:
    """Phase 3: Upload audio snippet and title to MP3 Manager.
    
    Uses pre-fetched uploaded_ids list to avoid re-uploading existing files.
    """
    basename = video_path.stem
    file_id = video_path.name
    title_path = get_title_path(temp_dir, basename)
    snippet_path = get_snippet_path(temp_dir, basename)
    
    # Precondition: title must exist
    if not title_path.exists():
        print(f"No title for {video_path.name}, skipping MP3 upload.")
        return False
    
    # Check if already uploaded using pre-fetched list
    if check_uploaded(file_id, uploaded_ids):
        print(f"Phase 3 already done for {video_path.name}, skipping upload (already on server).")
        return True
    
    # Upload
    def _perform() -> None:
        print(f"\n[3/{total_phases}] Uploading to MP3 Manager: {video_path.name}")
        title = title_path.read_text(encoding='utf-8').strip()
        if not title:
            raise ValueError(f"Empty title for {video_path.name}")
        
        client = Mp3ApiClient(os.getenv('MP3_MANAGER_URL'))
        try:
            result = client.upload(file_id, title, snippet_path)
            if result:
                print(f"  Uploaded: {file_id}")
            else:
                print(f"  Upload failed for {file_id}")
        finally:
            client.close()
    
    return _run_phase_step(
        video_path=video_path,
        already_done=False,
        already_done_message="",
        precondition_ok=_MP3_AVAILABLE and os.getenv('MP3_MANAGER_URL') is not None,
        precondition_message=f"MP3 Manager not configured, skipping upload for {video_path.name}.",
        work_fn=_perform,
        success_message=f"\n✓ Phase 3 (MP3 upload) done: {video_path.name}",
        failure_label="Phase 3",
    )


def run_output_phase(
    video_path: Path,
    output_dir: Path,
    temp_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
    encoder: VideoEncoderProfile,
    title_font: str | None = None,
    max_output_seconds: float | None = None,
    video_index: int = 1,
    total_videos: int = 1,
    enable_title_overlay: bool = False,
    enable_logo_overlay: bool = False,
    *,
    total_phases: int = 4,
) -> bool:
    """Phase 4: Full video trim with title-based output filename."""
    basename = video_path.stem
    title_path = get_title_path(temp_dir, basename)
    precondition_ok = True
    precondition_message = None
    chosen_basename: str | None = None
    title_text = ""

    already_done = is_completed(temp_dir, basename)
    if already_done:
        precondition_ok = False
        precondition_message = f"Phase 4 already done for {video_path.name}, skipping."
    elif not is_transcript_done(temp_dir, basename):
        precondition_ok = False
        precondition_message = (
            f"No transcript for {video_path.name}, skipping output phase."
        )
    elif not title_path.exists():
        precondition_ok = False
        precondition_message = f"No title for {video_path.name}, skipping output phase."
    else:
        title_text = title_path.read_text(encoding="utf-8").strip()
        if not title_text:
            precondition_ok = False
            precondition_message = f"Empty title for {video_path.name}, skipping output phase."
        else:
            chosen_basename = resolve_output_basename(title_text, output_dir)

    def _perform() -> None:
        assert chosen_basename is not None
        print(
            f"\n[4/{total_phases}] Creating final output: {video_path.name} -> {chosen_basename}.mp4"
        )
        output_mp4 = (output_dir / f"{chosen_basename}.mp4").resolve()
        trim_single_video(
            input_file=video_path,
            output_dir=output_dir,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
            target_length=target_length,
            output_basename=chosen_basename,
            encoder=encoder,
            title_path=title_path,
            title_font=title_font,
            max_output_seconds=max_output_seconds,
            enable_title_overlay=enable_title_overlay,
            enable_logo_overlay=enable_logo_overlay,
        )
        notify_final_output_ready(
            phase_index=4,
            total_phases=total_phases,
            video_index=video_index,
            total_videos=total_videos,
            input_name=video_path.name,
            title=title_text,
            output_mp4=output_mp4,
        )
        mark_completed(temp_dir, basename)

    return _run_phase_step(
        video_path=video_path,
        already_done=already_done,
        already_done_message=f"Phase 4 already done for {video_path.name}, skipping.",
        precondition_ok=precondition_ok,
        precondition_message=precondition_message,
        work_fn=_perform,
        success_message=f"\n✓ Phase 4 (output) done: {video_path.name}",
        failure_label="Phase 4",
    )


def run(args: argparse.Namespace | None = None) -> StartupContext:
    """Run the full three-phase media processing pipeline."""
    if args is None:
        args = parse_args()
    startup = build_startup_context(args)
    api_key = startup.api_key
    temp_dir = startup.temp_dir
    videos = startup.videos

    # MP3 Manager sync: fetch titles from API, update local .txt, trigger re-encodes
    if _MP3_AVAILABLE and os.getenv('MP3_MANAGER_URL'):
        try:
            client = Mp3ApiClient(os.getenv('MP3_MANAGER_URL'))
            titles_dir = temp_dir / 'titles'
            completed_dir = temp_dir / 'completed'
            updated = sync_titles(client, titles_dir, completed_dir)
            if updated:
                print(f"MP3 Manager: {len(updated)} title(s) updated from API, scheduled for re-encode")
            client.close()
        except Exception as e:
            print(f"MP3 Manager sync failed (continuing): {e}")

    enc = startup.encoder
    print(f"Resolved encoder: {enc.name} ({enc.codec})")
    quick_test_enabled = bool(getattr(args, "quick_test", False))
    max_output_seconds = QUICK_TEST_OUTPUT_SECONDS if quick_test_enabled else None
    if quick_test_enabled:
        print(
            f"Quick test mode enabled: limiting final output encodes to "
            f"{QUICK_TEST_OUTPUT_SECONDS:.0f}s."
        )

    print(f"Found {len(startup.videos)} video file(s)")
    print(f"Input: {startup.input_dir}")
    print(f"Output: {startup.output_dir}")
    print(f"Temp: {startup.temp_dir}")
    print("-" * 60)

    # Pre-fetch MP3 Manager uploaded files list for Phase 3 idempotency
    uploaded_ids: list[str] = []
    if _MP3_AVAILABLE and os.getenv('MP3_MANAGER_URL'):
        try:
            client = Mp3ApiClient(os.getenv('MP3_MANAGER_URL'))
            uploaded_ids = get_uploaded_file_ids(client)
            print(f"MP3 Manager: Fetched {len(uploaded_ids)} existing file(s) from server")
            client.close()
        except Exception as e:
            print(f"MP3 Manager: Failed to fetch file list (continuing): {e}")

    total_phases = 4
    phases = (
        _PipelinePhase(
            1,
            "Transcription",
            lambda video_file, _i, _n: run_transcription_phase(
                video_path=video_file,
                temp_dir=temp_dir,
                pad_sec=startup.pad_sec,
                api_key=api_key,
                total_phases=total_phases,
            ),
        ),
        _PipelinePhase(
            2,
            "Title Generation",
            lambda video_file, _i, _n: run_title_phase(
                video_path=video_file,
                temp_dir=temp_dir,
                api_key=api_key,
                total_phases=total_phases,
            ),
        ),
        _PipelinePhase(
            3,
            "MP3 Upload",
            lambda video_file, _i, _n: run_mp3_upload_phase(
                video_path=video_file,
                temp_dir=temp_dir,
                uploaded_ids=uploaded_ids,
                total_phases=total_phases,
            ),
        ),
        _PipelinePhase(
            4,
            "Final Output",
            lambda video_file, vi, vn: run_output_phase(
                video_path=video_file,
                output_dir=startup.output_dir,
                temp_dir=startup.temp_dir,
                noise_threshold=startup.noise_threshold,
                min_duration=startup.min_duration,
                pad_sec=startup.pad_sec,
                target_length=startup.target_length,
                encoder=startup.encoder,
                title_font=startup.title_font,
                max_output_seconds=max_output_seconds,
                video_index=vi,
                total_videos=vn,
                enable_title_overlay=startup.enable_title_overlay,
                enable_logo_overlay=startup.enable_logo_overlay,
                total_phases=total_phases,
            ),
        ),
    )

    for phase in phases:
        _run_phase(videos=videos, phase=phase, total_phases=len(phases))

    completed_dir = startup.temp_dir / COMPLETED_DIR
    completed = sum(1 for p in completed_dir.iterdir() if p.is_file())
    print(f"\n{'='*60}")
    print("Processing complete!")
    print(f"Completed: {completed}/{len(videos)}")
    print(f"{'='*60}")
    return startup
