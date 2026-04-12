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


# Module-level cache for Phase 3 bulk fetch (cleared after phase completes)
_audio_upload_cache: dict[str, set[str]] = {}


def run_audio_upload_phase(
    video_path: Path,
    temp_dir: Path,
    video_index: int,
    total_videos: int,
    media_manager_enabled: bool,
    *,
    total_phases: int = 5,
) -> bool | None:
    """Phase 3: Upload audio snippet to Media Manager for review.
    
    Uploads with tags=["todo"] so it appears in the TODO folder for review.
    Bulk fetches all audio files once at phase start for fast local lookup.
    Shows real-time status for all files (uploaded or skipped).
    """
    basename = video_path.stem
    file_id = basename  # Use basename without extension as the ID
    title_path = get_title_path(temp_dir, basename)
    snippet_path = get_snippet_path(temp_dir, basename)
    
    # Precondition: title must exist
    if not title_path.exists():
        return False
    
    # Precondition: snippet must exist
    if not snippet_path.exists():
        return False
    
    # Bulk fetch all audio files once at phase start (first call)
    cache_key = str(temp_dir)  # Unique per pipeline run
    if media_manager_enabled and cache_key not in _audio_upload_cache:
        print(f"[3/{total_phases}] Fetching audio list from server...")
        try:
            client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
            # Include trash files - they were already uploaded and should be skipped
            all_audio = client.get_audio_files(include_trash=True)
            uploaded_ids = {f.get('id') for f in all_audio if f.get('id')}
            _audio_upload_cache[cache_key] = uploaded_ids
            client.close()
            print(f"[3/{total_phases}] Found {len(uploaded_ids)} uploaded audio files")
        except Exception as e:
            print(f"[3/{total_phases}] \033[91mFailed to fetch audio list: {e}\033[0m")
            _audio_upload_cache[cache_key] = set()  # Empty set on failure
        # Clear cache at end of phase (last file)
        if video_index == total_videos:
            _audio_upload_cache.pop(cache_key, None)
    
    # Fast local lookup (no API call)
    uploaded_ids = _audio_upload_cache.get(cache_key, set())
    already_uploaded = file_id in uploaded_ids
    
    if already_uploaded:
        # Show status on single line that updates in-place
        short_name = video_path.name[:40] + "..." if len(video_path.name) > 40 else video_path.name
        print(f"\r[3/{total_phases}] [{video_index}/{total_videos}] {short_name} \033[90m✓ uploaded\033[0m\033[K", end='', flush=True)
        if video_index == total_videos:
            print()  # New line at phase end
        return None
    
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
        
        # Progress callback - single line that updates in place
        last_percent = -1
        def progress_callback(uploaded: int, total: int) -> None:
            nonlocal last_percent
            percent = int(uploaded * 100 / total)
            if percent != last_percent:
                mb_uploaded = uploaded / (1024 * 1024)
                # Use \r to overwrite same line, \033[K to clear to end
                print(f"\r  Uploading: {percent}% ({mb_uploaded:.1f}/{snippet_size_mb:.1f} MB)\033[K", end='', flush=True)
                last_percent = percent
        
        client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
        start_time = time.time()
        try:
            result = client.upload_audio(file_id, title, snippet_path, tags=['todo'],
                                         progress_callback=progress_callback)
            elapsed = time.time() - start_time
            speed_mbps = snippet_size_mb / elapsed if elapsed > 0 else 0
            if result:
                # \n to move to new line after progress bar
                print(f"\n  ✓ Uploaded in {elapsed:.1f}s ({speed_mbps:.1f} MB/s)")
            else:
                print(f"\n  \033[91m✗ Upload failed for {file_id} (server rejected)\033[0m")
        except Exception as e:
            # Show actual error details
            print(f"\n  \033[91m✗ Upload error for {file_id}: {e}\033[0m")
            raise  # Re-raise to trigger failure handling
        finally:
            client.close()
    
    return _run_phase_step(
        video_path=video_path,
        already_done=False,
        already_done_message="",
        precondition_ok=media_manager_enabled,
        precondition_message=None,  # Silenced - expected when Media Manager disabled
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


# Module-level cache for Phase 5 bulk fetch (cleared after phase completes)
_video_upload_cache: dict[str, dict[str, str]] = {}
# Cache for video existence check
_video_existence_cache: dict[str, set[str]] = {}


def run_video_upload_phase(
    video_path: Path,
    output_dir: Path,
    temp_dir: Path,
    video_index: int,
    total_videos: int,
    media_manager_enabled: bool,
    *,
    total_phases: int = 5,
) -> bool | None:
    """Phase 5: Upload final video to Media Manager (only if audio is approved).
    
    Only uploads when:
    1. The audio file_id is approved (has "ready" tag on server)
    2. A matching video file exists in output_dir
    
    Bulk fetches ready audio once at phase start for fast local lookup.
    Uses the APPROVED TITLE from the server (not local title.txt).
    Uploads with tags=["FB", "TT"] for Facebook and TikTok folders.
    """
    basename = video_path.stem
    file_id = basename
    
    # Bulk fetch all ready audio and uploaded videos once at phase start (first call)
    cache_key = str(temp_dir)  # Unique per pipeline run
    if media_manager_enabled and cache_key not in _video_upload_cache:
        print(f"[5/{total_phases}] Fetching ready audio list from server...")
        try:
            client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
            ready_audio = client.get_audio_files(tags='ready')
            ready_dict = {f.get('id'): f.get('title', '') for f in ready_audio if f.get('id')}
            _video_upload_cache[cache_key] = ready_dict
            client.close()
            print(f"[5/{total_phases}] Found {len(ready_dict)} ready audio files")
        except Exception as e:
            print(f"[5/{total_phases}] \033[91mFailed to fetch ready audio list: {e}\033[0m")
            _video_upload_cache[cache_key] = {}  # Empty dict on failure
    
    # Bulk fetch all uploaded videos once at phase start (first call)
    if media_manager_enabled and cache_key not in _video_existence_cache:
        print(f"[5/{total_phases}] Fetching video list from server...")
        try:
            client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
            all_videos = client.get_video_files()
            uploaded_video_ids = {f.get('id') for f in all_videos if f.get('id')}
            _video_existence_cache[cache_key] = uploaded_video_ids
            client.close()
            print(f"[5/{total_phases}] Found {len(uploaded_video_ids)} uploaded video files")
        except Exception as e:
            print(f"[5/{total_phases}] \033[91mFailed to fetch video list: {e}\033[0m")
            _video_existence_cache[cache_key] = set()  # Empty set on failure
        # Clear caches at end of phase (last file)
        if video_index == total_videos:
            _video_upload_cache.pop(cache_key, None)
            _video_existence_cache.pop(cache_key, None)
    
    # Fast local lookup (no API call)
    ready_dict = _video_upload_cache.get(cache_key, {})
    approved_title = ready_dict.get(file_id)
    
    short_name = video_path.name[:40] + "..." if len(video_path.name) > 40 else video_path.name
    
    if not approved_title:
        # Audio not approved yet - show status
        print(f"\r[5/{total_phases}] [{video_index}/{total_videos}] {short_name} \033[90m⏸ not ready\033[0m\033[K", end='', flush=True)
        if video_index == total_videos:
            print()  # New line at phase end
        return None
    
    # Compute expected output filename based on APPROVED title
    output_basename = sanitize_filename(approved_title)
    output_path = output_dir / f"{output_basename}.mp4"
    
    # Strict: file must exist with exact name derived from approved title
    if not output_path.exists():
        print(f"\n  [Error] Output file not found for {video_path.name}")
        print(f"    Expected: {output_path.name}")
        print(f"    Approved title (from API): {approved_title[:50]}...")
        print(f"    Output dir: {output_dir}")
        print(f"    ")
        print(f"    [CAUSE] Title was edited in UI but video not re-created")
        print(f"    [FIX] Delete completion marker and re-run Phase 4:")
        print(f"          del temp\\completed\\{video_path.stem}")
        print(f"    Then re-run the pipeline to re-encode with new title")
        return False
    
    # Fast local lookup: skip if video already uploaded (no API call)
    uploaded_video_ids = _video_existence_cache.get(cache_key, set())
    already_uploaded = file_id in uploaded_video_ids
    
    if already_uploaded:
        # Update same line with status, then clear at end
        print(f"\r[5/{total_phases}] [{video_index}/{total_videos}] {short_name} \033[90m✓ uploaded\033[0m\033[K", end='', flush=True)
        if video_index == total_videos:
            print()  # New line only at end of phase
        return None
    
    # Upload
    def _perform() -> None:
        video_size_mb = output_path.stat().st_size / (1024 * 1024)
        total_bytes = output_path.stat().st_size
        
        print(f"\n[5/{total_phases}] Uploading final video to Media Manager")
        print(f"  File: {output_path.name}")
        print(f"  Title (from API): {approved_title[:60]}{'...' if len(approved_title) > 60 else ''}")
        print(f"  Video size: {video_size_mb:.1f} MB")
        print(f"  Tags: [FB, TT]")
        
        # Progress callback - single line that updates in place
        last_percent = -1
        def progress_callback(uploaded: int, total: int) -> None:
            nonlocal last_percent
            percent = int(uploaded * 100 / total)
            if percent != last_percent:
                mb_uploaded = uploaded / (1024 * 1024)
                # Use \r to overwrite same line, \033[K to clear to end
                print(f"\r  Uploading: {percent}% ({mb_uploaded:.1f}/{video_size_mb:.1f} MB)\033[K", end='', flush=True)
                last_percent = percent
        
        client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
        start_time = time.time()
        try:
            result = client.upload_video(
                file_id, approved_title, output_path, tags=['FB', 'TT'],
                progress_callback=progress_callback,
                skip_if_exists_with_title=True
            )
            elapsed = time.time() - start_time
            speed_mbps = video_size_mb / elapsed if elapsed > 0 else 0
            if result.get('success'):
                # Only print when overwritten to keep terminal clean
                if result.get('overwritten'):
                    print(f"\n  ✓ Video uploaded (overwrote previous) in {elapsed:.1f}s ({speed_mbps:.1f} MB/s)")
                elif result.get('skipped'):
                    print()  # Just move to new line after progress bar, no message
                else:
                    print()  # Just move to new line after progress bar, no message
            else:
                error_msg = result.get('error', 'Unknown error')
                print(f"\n  \033[91m✗ Video upload failed for {file_id}: {error_msg}\033[0m")
        finally:
            client.close()
    
    return _run_phase_step(
        video_path=video_path,
        already_done=False,
        already_done_message="",
        precondition_ok=media_manager_enabled,
        precondition_message=None,  # Silenced - expected when Media Manager disabled
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
