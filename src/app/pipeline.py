"""Three-phase pipeline orchestration for SilenceRemover."""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
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
)
from sr_filename import sanitize_filename
from src.startup import StartupContext, build_startup_context
from src.ffmpeg.encoding_resolver import VideoEncoderProfile
from sr_snippet import create_silence_removed_snippet
from sr_telegram_notify import notify_audio_uploaded, notify_final_output_ready, notify_video_uploaded
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


# Unified server state cache for all server phases (cleared after each phase)
@dataclass
class ServerState:
    """Unified server state fetched once per phase."""
    # Phase 3: Audio
    audio_dict: dict[str, tuple[str, list]] = field(default_factory=dict)  # id -> (title, tags)
    audio_trash_ids: set[str] = field(default_factory=set)
    
    # Phase 5 & 6: Video
    video_dict: dict[str, tuple[str, list]] = field(default_factory=dict)  # id -> (title, tags)
    video_trash_ids: set[str] = field(default_factory=set)
    
    # Phase 6 only
    ready_audio_dict: dict[str, str] = field(default_factory=dict)  # id -> title


_server_state_cache: dict[str, ServerState] = {}


def run_audio_upload_phase(
    video_path: Path,
    temp_dir: Path,
    video_index: int,
    total_videos: int,
    media_manager_enabled: bool,
    *,
    total_phases: int = 7,
) -> bool | None:
    basename = video_path.stem
    file_id = basename
    title_path = get_title_path(temp_dir, basename)
    snippet_path = get_snippet_path(temp_dir, basename)
    
    if not title_path.exists():
        return None
    
    if not snippet_path.exists():
        return None
    
    title_text = title_path.read_text(encoding='utf-8').strip()
    if not title_text:
        return None
    
    if not media_manager_enabled:
        return None
    
    cache_key = str(temp_dir)
    if cache_key not in _server_state_cache:
        print(f"[3/{total_phases}] Fetching audio list from server...")
        try:
            client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
            all_audio = client.get_audio_files()
            state = ServerState()
            for audio in all_audio:
                aid = audio.get('id')
                if aid:
                    state.audio_dict[aid] = (audio.get('title', ''), audio.get('tags', []))
                    if 'trash' in audio.get('tags', []):
                        state.audio_trash_ids.add(aid)
            _server_state_cache[cache_key] = state
            client.close()
            print(f"[3/{total_phases}] Found {len(state.audio_dict)} audio files")
        except Exception as e:
            print(f"[3/{total_phases}] Failed to fetch: {e}")
            _server_state_cache[cache_key] = ServerState()
    
    if video_index == total_videos:
        _server_state_cache.pop(cache_key, None)
    
    state = _server_state_cache.get(cache_key, ServerState())
    
    if file_id in state.audio_trash_ids:
        short_name = video_path.name[:40] + "..." if len(video_path.name) > 40 else video_path.name
        print(f"\r[3/{total_phases}] [{video_index}/{total_videos}] {short_name} ✓ skip (trash)\033[K", end='', flush=True)
        if video_index == total_videos:
            print()
        return None
    
    if file_id in state.audio_dict:
        server_title, _ = state.audio_dict[file_id]
        if server_title == title_text:
            short_name = video_path.name[:40] + "..." if len(video_path.name) > 40 else video_path.name
            print(f"\r[3/{total_phases}] [{video_index}/{total_videos}] {short_name} ✓ uploaded\033[K", end='', flush=True)
            if video_index == total_videos:
                print()
            return None
        else:
            print(f"[3/{total_phases}] [{video_index}/{total_videos}] {video_path.name}: "
                  f"UPLOAD (title mismatch: server='{server_title[:30]}...' local='{title_text[:30]}...')")
    else:
        print(f"[3/{total_phases}] [{video_index}/{total_videos}] {video_path.name}: UPLOAD (not on server)")
    
    def _perform() -> None:
        client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
        try:
            total_size = snippet_path.stat().st_size
            upload_start_time = time.time()
            last_uploaded = 0
            
            def _upload_progress(uploaded_bytes: int, total_bytes: int) -> None:
                nonlocal upload_start_time, last_uploaded
                elapsed = time.time() - upload_start_time
                if elapsed > 0:
                    overall_speed = uploaded_bytes / elapsed
                    speed_mbps = overall_speed / (1024 * 1024)
                    percent = (uploaded_bytes / total_bytes) * 100 if total_bytes > 0 else 0
                    short_name = video_path.name[:40] + "..." if len(video_path.name) > 40 else video_path.name
                    print(f"\r[3/{total_phases}] [{video_index}/{total_videos}] {short_name} "
                          f"↑ {percent:5.1f}% {speed_mbps:5.2f} MB/s\033[K", end='', flush=True)
                    last_uploaded = uploaded_bytes
                    upload_start_time = time.time()
            
            result = client.upload_audio(
                file_id, title_text, snippet_path, 
                tags=['todo'],
                progress_callback=_upload_progress
            )
            if result:
                print(f"\n[3/{total_phases}] Uploaded: {video_path.name}")
                notify_audio_uploaded(
                    video_index=video_index,
                    total_videos=total_videos,
                    input_name=video_path.name,
                    title=title_text,
                )
        finally:
            client.close()
    
    return _run_phase_step(
        video_path=video_path,
        already_done=False,
        already_done_message="",
        precondition_ok=media_manager_enabled,
        precondition_message=None,
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
    
    if is_completed(temp_dir, basename):
        return None
    
    if not is_transcript_done(temp_dir, basename):
        return None
    
    if not title_path.exists():
        return None
    
    title_text = title_path.read_text(encoding="utf-8").strip()
    if not title_text:
        return None
    
    chosen_basename = sanitize_filename(title_text)

    def _perform() -> None:
        print(f"\n[4/{total_phases}] Creating final output: {video_path.name} -> {chosen_basename}.mp4")
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





def run_pending_upload_phase(
    video_path: Path,
    output_dir: Path,
    temp_dir: Path,
    video_index: int,
    total_videos: int,
    media_manager_enabled: bool,
    *,
    total_phases: int = 7,
) -> bool | None:
    basename = video_path.stem
    file_id = basename
    title_path = get_title_path(temp_dir, basename)
    
    if not is_completed(temp_dir, basename):
        return None
    
    if not title_path.exists():
        return None
    
    title_text = title_path.read_text(encoding='utf-8').strip()
    if not title_text:
        return None
    
    output_basename = sanitize_filename(title_text)
    output_path = output_dir / f"{output_basename}.mp4"
    
    if not media_manager_enabled:
        return None
    
    cache_key = str(temp_dir)
    if cache_key not in _server_state_cache:
        try:
            client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
            all_videos = client.get_video_files()
            state = ServerState()
            for video in all_videos:
                vid = video.get('id')
                if vid:
                    state.video_dict[vid] = (video.get('title', ''), video.get('tags', []))
                    if 'trash' in video.get('tags', []):
                        state.video_trash_ids.add(vid)
            _server_state_cache[cache_key] = state
            client.close()
            print(f"[5/{total_phases}] Fetched {len(state.video_dict)} videos from server "
                  f"({len(state.video_trash_ids)} in trash)")
        except Exception as e:
            print(f"[5/{total_phases}] Warning: Failed to fetch server state: {e}")
            _server_state_cache[cache_key] = ServerState()
    
    if video_index == total_videos:
        _server_state_cache.pop(cache_key, None)
    
    state = _server_state_cache.get(cache_key, ServerState())
    
    def _show_progress(status: str) -> None:
        short_name = video_path.name[:40] + "..." if len(video_path.name) > 40 else video_path.name
        print(f"\r[5/{total_phases}] [{video_index}/{total_videos}] {short_name} {status}\033[K", end='', flush=True)
        if video_index == total_videos:
            print()
    
    if file_id in state.video_trash_ids:
        _show_progress("✓ skip (trash)")
        return None
    
    if file_id in state.video_dict:
        server_title, server_tags = state.video_dict[file_id]
        if server_title == title_text:
            if 'pending' in server_tags:
                _show_progress("✓ skip (pending)")
                return None
            if 'FB' in server_tags or 'TT' in server_tags:
                _show_progress("✓ skip (published)")
                return None
            print(f"[5/{total_phases}] [{video_index}/{total_videos}] {video_path.name}: "
                  f"UPLOAD (exists but tags={server_tags})")
        else:
            print(f"[5/{total_phases}] [{video_index}/{total_videos}] {video_path.name}: "
                  f"UPLOAD (title mismatch: server='{server_title[:30]}...' "
                  f"local='{title_text[:30]}...')")
    else:
        print(f"[5/{total_phases}] [{video_index}/{total_videos}] {video_path.name}: "
              f"UPLOAD (not on server)")
    
    def _perform() -> None:
        client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
        try:
            total_size = output_path.stat().st_size
            upload_start_time = time.time()
            last_uploaded = 0
            
            def _upload_progress(uploaded_bytes: int, total_bytes: int) -> None:
                nonlocal upload_start_time, last_uploaded
                elapsed = time.time() - upload_start_time
                if elapsed > 0:
                    overall_speed = uploaded_bytes / elapsed
                    speed_mbps = overall_speed / (1024 * 1024)
                    percent = (uploaded_bytes / total_bytes) * 100 if total_bytes > 0 else 0
                    short_name = video_path.name[:40] + "..." if len(video_path.name) > 40 else video_path.name
                    print(f"\r[5/{total_phases}] [{video_index}/{total_videos}] {short_name} "
                          f"↑ {percent:5.1f}% {speed_mbps:5.2f} MB/s\033[K", end='', flush=True)
                    last_uploaded = uploaded_bytes
                    upload_start_time = time.time()
            
            client.upload_video(
                file_id, title_text, output_path, 
                tags=['pending'],
                progress_callback=_upload_progress
            )
            print(f"\n[5/{total_phases}] Staged to pending: {output_path.name}")
        finally:
            client.close()
    
    return _run_phase_step(
        video_path=video_path,
        already_done=False,
        already_done_message="",
        precondition_ok=media_manager_enabled,
        precondition_message=None,
        work_fn=_perform,
        success_message=f"\n✓ Phase 5 (stage) done: {video_path.name}",
        failure_label="Phase 5",
        phase_index=5,
        total_phases=total_phases,
        video_index=video_index,
        total_videos=total_videos,
        label="Stage to Pending",
    )


def run_video_upload_phase(
    video_path: Path,
    output_dir: Path,
    temp_dir: Path,
    video_index: int,
    total_videos: int,
    media_manager_enabled: bool,
    *,
    total_phases: int = 7,
) -> bool | None:
    basename = video_path.stem
    file_id = basename
    title_path = get_title_path(temp_dir, basename)
    
    if not is_completed(temp_dir, basename):
        return None
    
    if not title_path.exists():
        return None
    
    local_title = title_path.read_text(encoding='utf-8').strip()
    if not local_title:
        return None
    
    output_basename = sanitize_filename(local_title)
    output_path = output_dir / f"{output_basename}.mp4"
    
    if not media_manager_enabled:
        return None
    
    cache_key = str(temp_dir)
    if cache_key not in _server_state_cache:
        try:
            client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
            ready_audio = client.get_audio_files(tags='ready')
            all_videos = client.get_video_files()
            state = ServerState()
            for audio in ready_audio:
                aid = audio.get('id')
                if aid:
                    state.ready_audio_dict[aid] = audio.get('title', '')
            for video in all_videos:
                vid = video.get('id')
                if vid:
                    state.video_dict[vid] = (video.get('title', ''), video.get('tags', []))
                    if 'trash' in video.get('tags', []):
                        state.video_trash_ids.add(vid)
            _server_state_cache[cache_key] = state
            client.close()
            print(f"[6/{total_phases}] Fetched {len(state.ready_audio_dict)} ready audio, "
                  f"{len(state.video_dict)} videos from server "
                  f"({len(state.video_trash_ids)} in trash)")
        except Exception as e:
            print(f"[6/{total_phases}] Warning: Failed to fetch server state: {e}")
            _server_state_cache[cache_key] = ServerState()
    
    if video_index == total_videos:
        _server_state_cache.pop(cache_key, None)
    
    state = _server_state_cache.get(cache_key, ServerState())
    
    def _show_progress(status: str) -> None:
        short_name = video_path.name[:40] + "..." if len(video_path.name) > 40 else video_path.name
        print(f"\r[6/{total_phases}] [{video_index}/{total_videos}] {short_name} {status}\033[K", end='', flush=True)
        if video_index == total_videos:
            print()
    
    if file_id not in state.ready_audio_dict:
        _show_progress("✓ skip (audio not ready)")
        return None
    
    if file_id in state.video_trash_ids:
        _show_progress("✓ skip (trash)")
        return None
    
    if file_id in state.video_dict:
        server_title, server_tags = state.video_dict[file_id]
        if server_title == local_title:
            if 'FB' in server_tags or 'TT' in server_tags:
                _show_progress("✓ skip (published)")
                return None
            if 'pending' in server_tags:
                print(f"[6/{total_phases}] [{video_index}/{total_videos}] {video_path.name}: "
                      f"PUBLISH (currently pending)")
        else:
            print(f"[6/{total_phases}] [{video_index}/{total_videos}] {video_path.name}: "
                  f"PUBLISH (title mismatch: server='{server_title[:30]}...' "
                  f"local='{local_title[:30]}...')")
    else:
        print(f"[6/{total_phases}] [{video_index}/{total_videos}] {video_path.name}: "
              f"PUBLISH (not on server yet)")
    
    def _perform() -> None:
        client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
        try:
            total_size = output_path.stat().st_size
            upload_start_time = time.time()
            last_uploaded = 0
            
            def _upload_progress(uploaded_bytes: int, total_bytes: int) -> None:
                nonlocal upload_start_time, last_uploaded
                elapsed = time.time() - upload_start_time
                if elapsed > 0:
                    # Calculate speed from last chunk (instantaneous) and overall
                    bytes_since_last = uploaded_bytes - last_uploaded
                    instant_speed = bytes_since_last / elapsed if elapsed > 0 else 0
                    overall_speed = uploaded_bytes / elapsed
                    # Use overall speed for display (smoother)
                    speed_mbps = overall_speed / (1024 * 1024)
                    percent = (uploaded_bytes / total_bytes) * 100 if total_bytes > 0 else 0
                    short_name = video_path.name[:40] + "..." if len(video_path.name) > 40 else video_path.name
                    print(f"\r[6/{total_phases}] [{video_index}/{total_videos}] {short_name} "
                          f"↑ {percent:5.1f}% {speed_mbps:5.2f} MB/s\033[K", end='', flush=True)
                    last_uploaded = uploaded_bytes
                    upload_start_time = time.time()
            
            result = client.upload_video(
                file_id, local_title, output_path, 
                tags=['FB', 'TT'], 
                progress_callback=_upload_progress
            )
            
            if result.get('skipped'):
                _show_progress("✓ skip (already on server)")
            else:
                print(f"\n[6/{total_phases}] Published: {output_path.name}")
        finally:
            client.close()
    
    return _run_phase_step(
        video_path=video_path,
        already_done=False,
        already_done_message="",
        precondition_ok=media_manager_enabled,
        precondition_message=None,
        work_fn=_perform,
        success_message=f"\n✓ Phase 6 (publish) done: {video_path.name}",
        failure_label="Phase 6",
        phase_index=6,
        total_phases=total_phases,
        video_index=video_index,
        total_videos=total_videos,
        label="Publish Video",
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

    # PHASE 0: Filter short videos (skip if quick test mode)
    videos = startup.videos
    if not quick_test_enabled:
        from src.core.video_filter import filter_short_videos
        print(f"[0/7] Filtering videos shorter than {startup.skip_shorter_than}s...")
        videos, ignored = filter_short_videos(
            videos=videos,
            input_dir=startup.input_dir,
            min_duration_sec=startup.skip_shorter_than,
            temp_dir=temp_dir,
            total_phases=7,
        )
        print(f"[0/7] Complete: {len(videos)} videos kept, {len(ignored)} moved to ignored/")
    else:
        print(f"[0/7] Skipped (quick test mode)")
    
    if not videos:
        print("\nNo videos to process after filtering.")
        return startup

    total_phases = 7
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
            "Stage to Pending",
            lambda video_file, vi, vn, tp: run_pending_upload_phase(
                video_path=video_file,
                output_dir=startup.output_dir,
                temp_dir=temp_dir,
                video_index=vi,
                total_videos=vn,
                total_phases=tp,
                media_manager_enabled=media_manager_enabled,
            ),
        ),
        _PipelinePhase(
            6,
            "Publish Video",
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
