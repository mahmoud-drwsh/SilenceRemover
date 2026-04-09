"""Three-phase pipeline orchestration for SilenceRemover."""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.core.cli import parse_args
from src.core.constants import (
    AUDIO_EXTENSIONS,
    COMPLETED_DIR,
    SNIPPET_MAX_DURATION_SEC,
    TITLE_DIR,
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
from sr_filename import sanitize_filename
from src.startup import StartupContext, build_startup_context
from src.ffmpeg.encoding_resolver import VideoEncoderProfile
from sr_snippet import create_silence_removed_snippet
from sr_telegram_notify import notify_final_output_ready
from sr_title import generate_title_from_transcript
from sr_transcription import transcribe_and_save
from src.media.trim import trim_single_video

# Optional Media Manager integration for title sync and upload (Phases 3 and 5)
try:
    from sr_media_manager import (
        MediaManagerClient,
        sync_titles_from_api,
        get_ready_audio_ids,
        ensure_audio_uploaded,
        ensure_video_uploaded,
        get_uploaded_audio_ids,
        get_uploaded_video_ids,
    )
    _MEDIA_MANAGER_AVAILABLE = True
except ImportError:
    _MEDIA_MANAGER_AVAILABLE = False

QUICK_TEST_OUTPUT_SECONDS = 5.0


@dataclass(frozen=True)
class _PipelinePhase:
    index: int
    label: str
    run: Callable[[Path, int, int, int], bool | None]


def _run_phase(
    videos: list[Path], phase: _PipelinePhase, total_phases: int
) -> tuple[int, int, int]:
    """Run one phase over all videos with shared progress output.
    
    Returns: (success_count, skip_count, fail_count)
    """
    n = len(videos)
    success_count = 0
    skip_count = 0
    fail_count = 0
    for i, video_file in enumerate(videos, 1):
        # Call the phase function first - it will print its own header if work is needed
        result = phase.run(video_file, i, n, total_phases)
        if result is True:
            success_count += 1
        elif result is None:
            skip_count += 1
        else:
            fail_count += 1
    return success_count, skip_count, fail_count


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
    phase_index: int = 0,
    total_phases: int = 0,
    video_index: int = 0,
    total_videos: int = 0,
    label: str = "",
) -> bool | None:
    """Centralized phase execution wrapper with consistent skip/error behavior.
    
    Returns:
        True: Success
        None: Skipped (already done) - silent, no logging
        False: Failed or precondition not met
    """
    if already_done:
        # Silent skip - no individual logging, counted at phase level
        return None

    if not precondition_ok:
        if precondition_message is not None:
            print(precondition_message)
        return False

    # Print header when work actually starts
    if phase_index and total_phases and video_index and total_videos:
        print(f"\n{'='*60}")
        print(f"[{phase_index}/{total_phases}][{video_index}/{total_videos}] {label}: {video_path.name}")
        print(f"{'='*60}")

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
        print(f"\n\033[91m✗ {failure_label} error for {video_path.name}: {e}\033[0m", file=sys.stderr)
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
    video_index: int,
    total_videos: int,
    *,
    total_phases: int = 4,
) -> bool | None:
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
        phase_index=1,
        total_phases=total_phases,
        video_index=video_index,
        total_videos=total_videos,
        label="Transcription",
    )


def run_title_phase(
    video_path: Path,
    temp_dir: Path,
    api_key: str,
    video_index: int,
    total_videos: int,
    *,
    total_phases: int = 4,
) -> bool | None:
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
        phase_index=2,
        total_phases=total_phases,
        video_index=video_index,
        total_videos=total_videos,
        label="Title Generation",
    )


def run_audio_upload_phase(
    video_path: Path,
    temp_dir: Path,
    uploaded_audio_ids: list[str],
    video_index: int,
    total_videos: int,
    media_manager_enabled: bool,
    *,
    total_phases: int = 5,
) -> bool | None:
    """Phase 3: Upload audio snippet to Media Manager for review.
    
    Uploads with tags=["todo"] so it appears in the TODO folder for review.
    Uses pre-fetched uploaded_audio_ids list to avoid re-uploading existing files.
    """
    basename = video_path.stem
    file_id = basename  # Use basename without extension as the ID
    title_path = get_title_path(temp_dir, basename)
    snippet_path = get_snippet_path(temp_dir, basename)
    
    # Precondition: title must exist
    if not title_path.exists():
        return False
    
    # Check if already uploaded using pre-fetched list
    if file_id in uploaded_audio_ids:
        return None  # Silent skip
    
    # Upload
    def _perform() -> None:
        title = title_path.read_text(encoding='utf-8').strip()
        if not title:
            raise ValueError(f"Empty title for {video_path.name}")
        
        snippet_size_mb = snippet_path.stat().st_size / (1024 * 1024) if snippet_path.exists() else 0
        
        print(f"\n[3/{total_phases}] Uploading audio to Media Manager")
        print(f"  File: {video_path.name}")
        print(f"  Title: {title[:60]}{'...' if len(title) > 60 else ''}")
        print(f"  Audio snippet: {snippet_size_mb:.1f} MB")
        print(f"  Tags: [todo] (for review)")
        
        # Progress callback
        last_percent = -1
        def progress_callback(uploaded: int, total: int) -> None:
            nonlocal last_percent
            percent = int(uploaded * 100 / total)
            if percent != last_percent and percent % 20 == 0:  # Update every 20% for smaller files
                mb_uploaded = uploaded / (1024 * 1024)
                print(f"  Upload progress: {percent}% ({mb_uploaded:.1f}/{snippet_size_mb:.1f} MB)")
                last_percent = percent
        
        client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
        start_time = time.time()
        try:
            result = client.upload_audio(file_id, title, snippet_path, tags=['todo'],
                                         progress_callback=progress_callback)
            elapsed = time.time() - start_time
            speed_mbps = snippet_size_mb / elapsed if elapsed > 0 else 0
            if result:
                print(f"  ✓ Uploaded in {elapsed:.1f}s ({speed_mbps:.1f} MB/s)")
            else:
                print(f"  \033[91m✗ Upload failed for {file_id}\033[0m")
        finally:
            client.close()
    
    return _run_phase_step(
        video_path=video_path,
        already_done=False,
        already_done_message="",
        precondition_ok=media_manager_enabled,
        precondition_message=f"Media Manager not enabled, skipping audio upload for {video_path.name}.",
        work_fn=_perform,
        success_message=f"\n✓ Phase 3 (audio upload) done: {video_path.name}",
        failure_label="Phase 3",
        phase_index=3,
        total_phases=total_phases,
        video_index=video_index,
        total_videos=total_videos,
        label="Audio Upload",
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
    title_y_fraction: float | None = None,
    title_height_fraction: float | None = None,
    *,
    total_phases: int = 4,
) -> bool | None:
    """Phase 4: Full video trim with title-based output filename."""
    basename = video_path.stem
    title_path = get_title_path(temp_dir, basename)
    precondition_ok = True
    precondition_message = None
    chosen_basename: str | None = None
    title_text = ""

    already_done = is_completed(temp_dir, basename)
    if already_done:
        # Silent skip - counted at phase level
        return None
    
    if not is_transcript_done(temp_dir, basename):
        precondition_ok = False
        precondition_message = (
            f"\033[91mNo transcript for {video_path.name}, skipping output phase.\033[0m"
        )
    elif not title_path.exists():
        precondition_ok = False
        precondition_message = f"\033[91mNo title for {video_path.name}, skipping output phase.\033[0m"
    else:
        title_text = title_path.read_text(encoding="utf-8").strip()
        if not title_text:
            precondition_ok = False
            precondition_message = f"\033[91mEmpty title for {video_path.name}, skipping output phase.\033[0m"
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
            title_y_fraction=title_y_fraction,
            title_height_fraction=title_height_fraction,
            temp_dir=temp_dir,
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
        already_done=False,
        already_done_message="",
        precondition_ok=precondition_ok,
        precondition_message=precondition_message,
        work_fn=_perform,
        success_message=f"\n✓ Phase 4 (output) done: {video_path.name}",
        failure_label="Phase 4",
        phase_index=4,
        total_phases=total_phases,
        video_index=video_index,
        total_videos=total_videos,
        label="Final Output",
    )


def run_video_upload_phase(
    video_path: Path,
    output_dir: Path,
    temp_dir: Path,
    ready_audio_ids: list[str],
    uploaded_video_ids: list[str],
    video_index: int,
    total_videos: int,
    media_manager_enabled: bool,
    *,
    total_phases: int = 5,
) -> bool | None:
    """Phase 5: Upload final video to Media Manager (only if audio is approved).
    
    Only uploads when:
    1. The audio file_id is in ready_audio_ids (approved in UI)
    2. The video hasn't been uploaded yet (not in uploaded_video_ids)
    
    Uploads with tags=["FB", "TT"] for Facebook and TikTok folders.
    """
    basename = video_path.stem
    file_id = basename
    title_path = get_title_path(temp_dir, basename)
    
    # Check if audio is approved (ready)
    if file_id not in ready_audio_ids:
        # Audio not approved yet - skip silently
        return None
    
    # Check if video already uploaded
    if file_id in uploaded_video_ids:
        return None  # Already uploaded
    
    # Precondition: title must exist
    if not title_path.exists():
        return False
    
    # Read title from source of truth (title.txt)
    title = title_path.read_text(encoding='utf-8').strip()
    
    # Compute expected output filename based on current title
    # Phase 4 creates: {sanitized_title}.mp4 (exact match, no suffix)
    output_basename = sanitize_filename(title)
    output_path = output_dir / f"{output_basename}.mp4"
    
    # Strict: file must exist with exact name derived from current title
    if not output_path.exists():
        print(f"\n  [Error] Output file not found for {video_path.name}")
        print(f"    Expected: {output_path.name}")
        print(f"    Title (from title.txt): {title[:50]}...")
        print(f"    Output dir: {output_dir}")
        print(f"    ")
        print(f"    [CAUSE] Title was edited but video not re-created")
        print(f"    [FIX] Delete completion marker and re-run Phase 4:")
        print(f"          del temp\\completed\\{video_path.stem}")
        print(f"    Then re-run the pipeline to re-encode with new title")
        return False
    
    # Upload
    def _perform() -> None:
        video_size_mb = output_path.stat().st_size / (1024 * 1024)
        total_bytes = output_path.stat().st_size
        
        print(f"\n[5/{total_phases}] Uploading final video to Media Manager")
        print(f"  File: {output_path.name}")
        print(f"  Title: {title[:60]}{'...' if len(title) > 60 else ''}")
        print(f"  Video size: {video_size_mb:.1f} MB")
        print(f"  Tags: [FB, TT]")
        
        # Progress callback
        last_percent = -1
        def progress_callback(uploaded: int, total: int) -> None:
            nonlocal last_percent
            percent = int(uploaded * 100 / total)
            if percent != last_percent and percent % 10 == 0:  # Update every 10%
                mb_uploaded = uploaded / (1024 * 1024)
                print(f"  Upload progress: {percent}% ({mb_uploaded:.1f}/{video_size_mb:.1f} MB)")
                last_percent = percent
        
        client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
        start_time = time.time()
        try:
            result = client.upload_video(file_id, title, output_path, tags=['FB', 'TT'], 
                                        progress_callback=progress_callback)
            elapsed = time.time() - start_time
            speed_mbps = video_size_mb / elapsed if elapsed > 0 else 0
            if result:
                print(f"  ✓ Video uploaded in {elapsed:.1f}s ({speed_mbps:.1f} MB/s)")
            else:
                print(f"  \033[91m✗ Video upload failed for {file_id}\033[0m")
        finally:
            client.close()
    
    return _run_phase_step(
        video_path=video_path,
        already_done=False,
        already_done_message="",
        precondition_ok=media_manager_enabled,
        precondition_message=f"Media Manager not enabled, skipping video upload for {video_path.name}.",
        work_fn=_perform,
        success_message=f"\n✓ Phase 5 (video upload) done: {video_path.name}",
        failure_label="Phase 5",
        phase_index=5,
        total_phases=total_phases,
        video_index=video_index,
        total_videos=total_videos,
        label="Video Upload",
    )


def run(args: argparse.Namespace | None = None) -> StartupContext:
    """Run the full three-phase media processing pipeline."""
    if args is None:
        args = parse_args()
    startup = build_startup_context(args)
    api_key = startup.api_key
    temp_dir = startup.temp_dir
    videos = startup.videos

    # Media Manager two-way sync: fetch titles from API, update local .txt, trigger re-encodes
    media_manager_enabled = (
        getattr(args, "enable_media_manager", False) and
        _MEDIA_MANAGER_AVAILABLE and
        os.getenv('MEDIA_MANAGER_URL')
    )
    if media_manager_enabled:
        print(f"\n[Media Manager] Two-way sync: fetching titles from server...")
        try:
            client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
            titles_dir = temp_dir / TITLE_DIR
            completed_dir = temp_dir / 'completed'
            updated = sync_titles_from_api(client, titles_dir, completed_dir, startup.output_dir)
            if updated:
                print(f"  [Media Manager] {len(updated)} title(s) updated from API:")
                for file_id, old_title, new_title in updated:
                    old_short = old_title[:30] + '...' if len(old_title) > 30 else old_title
                    new_short = new_title[:30] + '...' if len(new_title) > 30 else new_title
                    print(f"    • {file_id}:")
                    print(f"      Old: '{old_short}'")
                    print(f"      New: '{new_short}'")
            else:
                print(f"  [Media Manager] No title updates from server")
            client.close()
            print(f"  [Media Manager] Sync complete")
        except Exception as e:
            print(f"  \033[91m[Media Manager] Sync failed (continuing): {e}\033[0m")

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

    # Pre-fetch Media Manager data for Phase 3 and 5 idempotency
    uploaded_audio_ids: list[str] = []
    uploaded_video_ids: list[str] = []
    ready_audio_ids: list[str] = []
    if media_manager_enabled:
        try:
            client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
            # For Phase 3: check which audio files already uploaded
            uploaded_audio_ids = get_uploaded_audio_ids(client)
            print(f"Media Manager: Fetched {len(uploaded_audio_ids)} existing audio file(s) from server")
            # For Phase 5: check which videos already uploaded and which audio is ready
            uploaded_video_ids = get_uploaded_video_ids(client)
            ready_audio_ids = get_ready_audio_ids(client)
            print(f"Media Manager: Fetched {len(uploaded_video_ids)} existing video file(s)")
            print(f"Media Manager: {len(ready_audio_ids)} audio file(s) marked as 'ready' for video upload")
            client.close()
        except Exception as e:
            print(f"Media Manager: Failed to fetch file list (continuing): {e}")

    total_phases = 5
    phases = (
        _PipelinePhase(
            1,
            "Transcription",
            lambda video_file, vi, vn, tp: run_transcription_phase(
                video_path=video_file,
                temp_dir=temp_dir,
                pad_sec=startup.pad_sec,
                api_key=api_key,
                video_index=vi,
                total_videos=vn,
                total_phases=tp,
            ),
        ),
        _PipelinePhase(
            2,
            "Title Generation",
            lambda video_file, vi, vn, tp: run_title_phase(
                video_path=video_file,
                temp_dir=temp_dir,
                api_key=api_key,
                video_index=vi,
                total_videos=vn,
                total_phases=tp,
            ),
        ),
        _PipelinePhase(
            3,
            "Audio Upload",
            lambda video_file, vi, vn, tp: run_audio_upload_phase(
                video_path=video_file,
                temp_dir=temp_dir,
                uploaded_audio_ids=uploaded_audio_ids,
                video_index=vi,
                total_videos=vn,
                media_manager_enabled=media_manager_enabled,
                total_phases=tp,
            ),
        ),
        _PipelinePhase(
            4,
            "Final Output",
            lambda video_file, vi, vn, tp: run_output_phase(
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
                title_y_fraction=getattr(args, 'title_y_fraction', None),
                title_height_fraction=getattr(args, 'title_height_fraction', None),
                total_phases=tp,
            ),
        ),
        _PipelinePhase(
            5,
            "Video Upload",
            lambda video_file, vi, vn, tp: run_video_upload_phase(
                video_path=video_file,
                output_dir=startup.output_dir,
                temp_dir=temp_dir,
                ready_audio_ids=ready_audio_ids,
                uploaded_video_ids=uploaded_video_ids,
                video_index=vi,
                total_videos=vn,
                total_phases=tp,
                media_manager_enabled=media_manager_enabled,
            ),
        ),
    )

    for phase in phases:
        success, skipped, failed = _run_phase(videos=videos, phase=phase, total_phases=len(phases))
        # Phase summary
        summary_parts = []
        if success:
            summary_parts.append(f"{success} done")
        if skipped:
            summary_parts.append(f"{skipped} skipped (already done)")
        if failed:
            summary_parts.append(f"\033[91m{failed} failed\033[0m")
        summary = ", ".join(summary_parts) if summary_parts else "nothing to do"
        print(f"\n[Phase {phase.index} complete] {summary}")

    completed_dir = startup.temp_dir / COMPLETED_DIR
    completed = sum(1 for p in completed_dir.iterdir() if p.is_file())
    print(f"\n{'='*60}")
    print("Processing complete!")
    print(f"Completed: {completed}/{len(videos)}")
    print(f"{'='*60}")
    return startup
