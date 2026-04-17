"""Nine-phase pipeline orchestration for SilenceRemover."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, TextIO


from src.core.cli import parse_args
from src.core.constants import (
    AUDIO_EXTENSIONS,
    SNIPPET_MAX_DURATION_SEC,
    TITLE_DIR,
)
from src.core.paths import (
    get_completed_output_filename,
    get_snippet_path,
    get_title_path,
    get_transcript_path,
    is_completed,
    is_overlay_done,
    is_snippet_done,
    is_title_done,
    is_transcript_done,
    mark_completed,
)
from sr_filename import sanitize_filename
from src.startup import StartupContext, build_startup_context

from sr_snippet import create_silence_removed_snippet
from sr_telegram_notify import (
    notify_audio_uploaded,
    notify_final_encoding_started,
    notify_final_output_ready,
)
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
    run: Callable[[Path, int, int], bool | None]
    skip_reason: Callable[[Path], str | None] | None = None


class _ConsolePhaseProgress:
    """TTY-aware phase progress output with compact single-line updates."""

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self._is_tty = bool(getattr(stream, "isatty", lambda: False)())
        self._current_phase: str | None = None
        self._compact_line_active = False

    def start_phase(self, label: str) -> None:
        if self._current_phase == label:
            return
        self.finish_line()
        self.stream.write("\n")
        self.stream.flush()
        self._current_phase = label

    def show_file_progress(self, label: str, video_index: int, total_videos: int, name: str) -> None:
        self.start_phase(label)
        message = f"[{label}] File {video_index}/{total_videos}: {name}"
        if self._is_tty:
            self.stream.write(f"\r{message}\033[K")
            self._compact_line_active = True
        else:
            self.stream.write(f"{message}\n")
        self.stream.flush()

    def finish_line(self) -> None:
        if not self._compact_line_active:
            return
        self.stream.write("\n")
        self.stream.flush()
        self._compact_line_active = False


_PHASE_PROGRESS: _ConsolePhaseProgress | None = None


def _get_phase_progress() -> _ConsolePhaseProgress:
    """Return a phase progress helper bound to the current stdout."""
    global _PHASE_PROGRESS
    if _PHASE_PROGRESS is None or _PHASE_PROGRESS.stream is not sys.stdout:
        _PHASE_PROGRESS = _ConsolePhaseProgress(sys.stdout)
    return _PHASE_PROGRESS


def _run_phase(
    videos: list[Path], phase: _PipelinePhase
) -> tuple[int, int, int]:
    """Run one phase over all videos.
    
    Returns: (success_count, skip_count, fail_count)
    """
    n = len(videos)
    success_count = 0
    skip_count = 0
    fail_count = 0
    phase_progress = _get_phase_progress()
    phase_progress.start_phase(phase.label)

    for i, video_file in enumerate(videos, 1):
        if phase.skip_reason is not None:
            reason = phase.skip_reason(video_file)
            if reason:
                skip_count += 1
                phase_progress.stream.write(f"  skip: {video_file.name} ({reason})\n")
                continue
        result = phase.run(video_file, i, n)
        if result is True:
            success_count += 1
        elif result is None:
            skip_count += 1
        else:
            fail_count += 1

    phase_progress.finish_line()
    
    return success_count, skip_count, fail_count


def _run_phase_step(
    video_path: Path,
    work_fn: Callable[[], None],
    video_index: int,
    total_videos: int,
    label: str,
) -> bool | None:
    """Execute a single phase step."""
    stream = _get_phase_progress().stream
    stream.write(f"  processing: {video_path.name}\n")
    stream.flush()
    _get_phase_progress().show_file_progress(label, video_index, total_videos, video_path.name)

    try:
        work_fn()
        return True
    except ValueError:
        _get_phase_progress().finish_line()
        return False
    except Exception:
        _get_phase_progress().finish_line()
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

    transcribe_and_save(
        api_key=api_key,
        audio_path=resolved,
        output_path=transcript_path,
        log_dir=temp_dir,
    )


def generate_title(
    temp_dir: Path, api_key: str, basename: str
) -> None:
    """Generate title from transcript file and save to file."""
    transcript_path = get_transcript_path(temp_dir, basename)
    title_path = get_title_path(temp_dir, basename)

    generate_title_from_transcript(
        api_key=api_key,
        transcript_path=transcript_path,
        output_path=title_path,
        log_dir=temp_dir,
    )


def run_snippet_phase(
    video_path: Path,
    temp_dir: Path,
    pad_sec: float,
    video_index: int,
    total_videos: int,
) -> bool | None:
    """Phase 1: Create silence-removed snippet to `temp/snippet/{basename}.ogg`."""
    basename = video_path.stem
    snippet_path = get_snippet_path(temp_dir, basename)

    def _perform() -> None:
        create_silence_removed_snippet(
            input_file=video_path,
            output_audio_path=snippet_path,
            temp_dir=temp_dir,
            pad_sec=pad_sec,
            max_duration=SNIPPET_MAX_DURATION_SEC,
        )

    return _run_phase_step(
        video_path=video_path,
        work_fn=_perform,
        video_index=video_index,
        total_videos=total_videos,
        label="Snippet Creation",
    )


def run_transcription_phase(
    video_path: Path,
    temp_dir: Path,
    pad_sec: float,
    api_key: str,
    video_index: int,
    total_videos: int,
) -> bool | None:
    """Phase 2: Transcribe existing snippet to `temp/transcript/{basename}.txt`."""
    basename = video_path.stem
    snippet_path = get_snippet_path(temp_dir, basename)

    def _perform() -> None:
        transcribe_media(audio_path=snippet_path, temp_dir=temp_dir, api_key=api_key, basename=basename)

    return _run_phase_step(
        video_path=video_path,
        work_fn=_perform,
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
) -> bool | None:
    """Phase 3: Generate title from transcript to `temp/title/{basename}.txt`."""
    basename = video_path.stem

    def _perform() -> None:
        generate_title(temp_dir=temp_dir, api_key=api_key, basename=basename)

    return _run_phase_step(
        video_path=video_path,
        work_fn=_perform,
        video_index=video_index,
        total_videos=total_videos,
        label="Title Generation",
    )


def run_overlay_phase(
    video_path: Path,
    temp_dir: Path,
    title_font: str | None,
    video_index: int,
    total_videos: int,
    enable_title_overlay: bool = False,
    enable_logo_overlay: bool = False,
    title_y_fraction: float | None = None,
    title_height_fraction: float | None = None,
) -> bool | None:
    """Phase 5: Generate title overlay PNG and pre-scale logo."""
    from src.media.trim import prepare_video_overlays
    from src.core.paths import get_title_path, is_title_done, is_overlay_done, mark_overlay_done

    basename = video_path.stem
    title_path = get_title_path(temp_dir, basename)

    def _perform() -> None:
        # Read title content for the marker (overlay invalidates if title changes)
        title_text = title_path.read_text(encoding="utf-8").strip()
        
        prepare_video_overlays(
            input_file=video_path,
            temp_dir=temp_dir,
            title_path=title_path,
            title_font=title_font,
            enable_title_overlay=enable_title_overlay,
            enable_logo_overlay=enable_logo_overlay,
            title_y_fraction=title_y_fraction,
            title_height_fraction=title_height_fraction,
        )
        mark_overlay_done(temp_dir, basename, title_text)

    return _run_phase_step(
        video_path=video_path,
        work_fn=_perform,
        video_index=video_index,
        total_videos=total_videos,
        label="Overlay Generation",
    )


@dataclass(frozen=True)
class ServerDataCache:
    """Unified server data fetched once at pipeline start."""
    audio_files: dict[str, dict]
    video_files: dict[str, dict]
    audio_trash_ids: frozenset[str]
    video_trash_ids: frozenset[str]
    ready_audio_ids: frozenset[str]
    
    @property
    def audio_count(self) -> int:
        return len(self.audio_files)
    
    @property
    def video_count(self) -> int:
        return len(self.video_files)
    
    def get_audio(self, file_id: str) -> dict | None:
        return self.audio_files.get(file_id)
    
    def get_video(self, file_id: str) -> dict | None:
        return self.video_files.get(file_id)
    
    def is_audio_trash(self, file_id: str) -> bool:
        return file_id in self.audio_trash_ids
    
    def is_video_trash(self, file_id: str) -> bool:
        return file_id in self.video_trash_ids
    
    def is_audio_ready(self, file_id: str) -> bool:
        return file_id in self.ready_audio_ids


_server_data_cache: ServerDataCache | None = None


def run_audio_upload_phase(
    video_path: Path,
    temp_dir: Path,
    video_index: int,
    total_videos: int,
    server_cache: ServerDataCache | None,
) -> bool | None:
    basename = video_path.stem
    file_id = basename
    title_path = get_title_path(temp_dir, basename)
    snippet_path = get_snippet_path(temp_dir, basename)
    
    def _perform() -> None:
        fresh_title = title_path.read_text(encoding='utf-8').strip()
        client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
        try:
            result = client.upload_audio(
                file_id, fresh_title, snippet_path, 
                tags=['todo'],
                progress_callback=None
            )
            if result:
                notify_audio_uploaded(
                    video_index=video_index,
                    total_videos=total_videos,
                    input_name=video_path.name,
                    title=fresh_title,
                )
        finally:
            client.close()
    
    return _run_phase_step(
        video_path=video_path,
        work_fn=_perform,
        video_index=video_index,
        total_videos=total_videos,
        label="Audio Upload",
    )


def run_encode_phase(
    video_path: Path,
    output_dir: Path,
    temp_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
    encoder: str,
    title_font: str | None = None,
    max_output_seconds: float | None = None,
    video_index: int = 1,
    total_videos: int = 1,
    enable_title_overlay: bool = False,
    enable_logo_overlay: bool = False,
) -> bool | None:
    """Phase 6: Full video trim with title-based output filename."""
    basename = video_path.stem
    title_path = get_title_path(temp_dir, basename)

    title_text = title_path.read_text(encoding="utf-8").strip()

    chosen_basename = sanitize_filename(title_text)
    clean_title = title_text

    def _perform() -> None:
        notify_final_encoding_started(
            video_index=video_index,
            total_videos=total_videos,
            input_name=video_path.name,
            title=title_text,
        )
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
            temp_dir=temp_dir,
            metadata_title=clean_title,
        )
        notify_final_output_ready(
            video_index=video_index,
            total_videos=total_videos,
            input_name=video_path.name,
            title=title_text,
        )
        mark_completed(temp_dir, basename, output_filename=chosen_basename)

    return _run_phase_step(
        video_path=video_path,
        work_fn=_perform,
        video_index=video_index,
        total_videos=total_videos,
        label="Final Encode",
    )


def run_video_reconciliation_phase(
    video_path: Path,
    video_index: int,
    total_videos: int,
    server_cache: ServerDataCache | None,
    *,
    temp_dir: Path,
) -> bool | None:
    """Phase 7: Reconcile - delete server video if local title differs."""
    basename = video_path.stem
    file_id = basename
    
    def _perform() -> None:
        client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
        try:
            client.update_tags(file_id, ['trash'], file_type='video')
            client.delete_file(file_id, file_type='video')
        finally:
            client.close()

    return _run_phase_step(
        video_path=video_path,
        work_fn=_perform,
        video_index=video_index,
        total_videos=total_videos,
        label="Video Reconciliation",
    )


def _rebuild_server_cache(media_manager_url: str) -> ServerDataCache | None:
    """Rebuild server cache from API. Used between phases to get fresh server state."""
    try:
        client = MediaManagerClient(media_manager_url)
        try:
            all_audio = client.get_audio_files(include_trash=True)
            all_videos = client.get_video_files(include_trash=True)

            audio_files = {}
            audio_trash = set()
            ready_audio = set()

            for audio in all_audio:
                aid = audio.get('id')
                if aid:
                    audio_files[aid] = audio
                    tags = audio.get('tags', [])
                    if isinstance(tags, list):
                        if 'trash' in tags:
                            audio_trash.add(aid)
                        if 'ready' in tags:
                            ready_audio.add(aid)

            video_files = {}
            video_trash = set()

            for video in all_videos:
                vid = video.get('id')
                if vid:
                    video_files[vid] = video
                    tags = video.get('tags', [])
                    if isinstance(tags, list) and 'trash' in tags:
                        video_trash.add(vid)

            return ServerDataCache(
                audio_files=audio_files,
                video_files=video_files,
                audio_trash_ids=frozenset(audio_trash),
                video_trash_ids=frozenset(video_trash),
                ready_audio_ids=frozenset(ready_audio),
            )
        finally:
            client.close()
    except Exception:
        return None


def run_video_upload_phase(
    video_path: Path,
    output_dir: Path,
    temp_dir: Path,
    video_index: int,
    total_videos: int,
    server_cache: ServerDataCache | None,
) -> bool | None:
    """Phase 8: Upload video with ['pending'] tags.

    Logic:
    - If server_cache is None → return None (skip)
    - If not completed locally → return None (skip)
    - If no local title → return None (skip)
    - If video exists with FB/TT tags → return None (already published)
    - If video exists with pending tags → return None (will be promoted in Phase 9)
    - If video exists with different title → return None (Phase 7 handles reconciliation)
    - If video is in trash → return None (skip — do not re-upload trashed content)
    - If video not on server → upload with tags=['pending']
    """
    basename = video_path.stem
    file_id = basename
    title_path = get_title_path(temp_dir, basename)

    local_title = title_path.read_text(encoding='utf-8').strip()

    # Read output filename from completion marker (Phase 6 stores it there)
    output_basename = get_completed_output_filename(temp_dir, basename)
    if output_basename is None:
        # Fallback: try to construct from title (for backwards compatibility)
        output_basename = sanitize_filename(local_title)
    output_path = output_dir / f"{output_basename}.mp4"

    def _perform() -> None:
        client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
        try:
            client.upload_video(
                file_id, local_title, output_path,
                tags=['pending'],
                progress_callback=None
            )
        finally:
            client.close()
    
    return _run_phase_step(
        video_path=video_path,
        work_fn=_perform,
        video_index=video_index,
        total_videos=total_videos,
        label="Video Upload",
    )


def run_video_tag_promotion_phase(
    video_path: Path,
    output_dir: Path,
    temp_dir: Path,
    video_index: int,
    total_videos: int,
    server_cache: ServerDataCache | None,
) -> bool | None:
    """Phase 9: Promote video tags from pending to ['FB', 'TT'] when audio is approved."""
    basename = video_path.stem
    file_id = basename

    def _perform() -> None:
        client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
        try:
            client.update_tags(file_id, ['FB', 'TT'], file_type='video')
        finally:
            client.close()

    return _run_phase_step(
        video_path=video_path,
        work_fn=_perform,
        video_index=video_index,
        total_videos=total_videos,
        label="Tag Promotion",
    )


def run(args: argparse.Namespace | None = None) -> StartupContext:
    """Run the full nine-phase media processing pipeline."""
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
        try:
            client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))
            titles_dir = temp_dir / TITLE_DIR
            completed_dir = temp_dir / 'completed'
            sync_titles_from_api(client, titles_dir, completed_dir, startup.output_dir)
            client.close()
        except Exception:
            pass

    # Fetch all server data once for all phases
    server_cache = None
    if media_manager_enabled:
        server_cache = _rebuild_server_cache(os.getenv('MEDIA_MANAGER_URL') or '')

    quick_test_enabled = bool(getattr(args, "quick_test", False))
    max_output_seconds = QUICK_TEST_OUTPUT_SECONDS if quick_test_enabled else None

    videos = startup.videos
    if not videos:
        return startup

    def _title_text(video_file: Path) -> str:
        title_path = get_title_path(temp_dir, video_file.stem)
        if not title_path.exists():
            return ""
        return title_path.read_text(encoding="utf-8").strip()

    def _audio_meta(video_file: Path) -> dict:
        if server_cache is None:
            return {}
        audio = server_cache.get_audio(video_file.stem)
        return audio if isinstance(audio, dict) else {}

    def _video_meta(video_file: Path) -> dict:
        if server_cache is None:
            return {}
        video = server_cache.get_video(video_file.stem)
        return video if isinstance(video, dict) else {}

    phases = (
        # NEW: Phase 1 - Snippet Creation
        _PipelinePhase(
            1,
            "Snippet Creation",
            lambda video_file, vi, vn: run_snippet_phase(
                video_path=video_file,
                temp_dir=temp_dir,
                pad_sec=startup.pad_sec,
                video_index=vi,
                total_videos=vn,
            ),
            skip_reason=lambda video_file: (
                "snippet already exists"
                if is_snippet_done(temp_dir, video_file.stem)
                else None
            ),
        ),
        # UPDATED: Phase 2 - Transcription (was Phase 1)
        _PipelinePhase(
            2,
            "Transcription",
            lambda video_file, vi, vn: run_transcription_phase(
                video_path=video_file,
                temp_dir=temp_dir,
                pad_sec=startup.pad_sec,
                api_key=api_key,
                video_index=vi,
                total_videos=vn,
            ),
            skip_reason=lambda video_file: (
                "transcript already exists"
                if is_transcript_done(temp_dir, video_file.stem)
                else (
                    "snippet missing (run phase 1 first)"
                    if not is_snippet_done(temp_dir, video_file.stem)
                    else None
                )
            ),
        ),
        # UPDATED: Phase 3 - Title Generation (was Phase 2)
        _PipelinePhase(
            3,
            "Title Generation",
            lambda video_file, vi, vn: run_title_phase(
                video_path=video_file,
                temp_dir=temp_dir,
                api_key=api_key,
                video_index=vi,
                total_videos=vn,
            ),
            skip_reason=lambda video_file: (
                "title already exists"
                if is_title_done(temp_dir, video_file.stem)
                else (
                    "transcript missing (run phase 2 first)"
                    if not is_transcript_done(temp_dir, video_file.stem)
                    else None
                )
            ),
        ),
        # UPDATED: Phase 4 - Audio Upload (was Phase 3)
        _PipelinePhase(
            4,
            "Audio Upload",
            lambda video_file, vi, vn: run_audio_upload_phase(
                video_path=video_file,
                temp_dir=temp_dir,
                video_index=vi,
                total_videos=vn,
                server_cache=server_cache,
            ),
            skip_reason=lambda video_file: (
                "media manager disabled"
                if server_cache is None
                else (
                    "audio marked trash on server"
                    if server_cache.is_audio_trash(video_file.stem)
                    else (
                        "snippet/title missing (run phases 2-3 first)"
                        if not (
                            is_title_done(temp_dir, video_file.stem)
                            and is_snippet_done(temp_dir, video_file.stem)
                        )
                        else (
                            "audio already uploaded with same title"
                            if _audio_meta(video_file).get("title", "").strip() == _title_text(video_file)
                            and _audio_meta(video_file)
                            else None
                        )
                    )
                )
            ),
        ),
        # UPDATED: Phase 5 - Overlay Generation
        _PipelinePhase(
            5,
            "Overlay Generation",
            lambda video_file, vi, vn: run_overlay_phase(
                video_file,
                temp_dir,
                title_font=startup.title_font,
                video_index=vi,
                total_videos=vn,
                enable_title_overlay=startup.enable_title_overlay,
                enable_logo_overlay=startup.enable_logo_overlay,
                title_y_fraction=getattr(args, 'title_y_fraction', None),
                title_height_fraction=getattr(args, 'title_height_fraction', None),
            ),
            skip_reason=lambda video_file: (
                "title missing (run phase 3 first)"
                if not is_title_done(temp_dir, video_file.stem)
                else (
                    "overlay already generated for current title"
                    if is_overlay_done(temp_dir, video_file.stem)
                    else None
                )
            ),
        ),
        # UPDATED: Phase 6 - Final Encode (was Phase 5)
        _PipelinePhase(
            6,
            "Final Encode",
            lambda video_file, vi, vn: run_encode_phase(
                video_path=video_file,
                output_dir=startup.output_dir,
                temp_dir=startup.temp_dir,
                noise_threshold=startup.noise_threshold,
                min_duration=startup.min_duration,
                pad_sec=startup.pad_sec,
                target_length=startup.target_length,
                encoder=args.encoder,
                title_font=startup.title_font,
                max_output_seconds=max_output_seconds,
                video_index=vi,
                total_videos=vn,
                enable_title_overlay=startup.enable_title_overlay,
                enable_logo_overlay=startup.enable_logo_overlay,
            ),
            skip_reason=lambda video_file: (
                "already completed"
                if is_completed(temp_dir, video_file.stem)
                else (
                    "transcript missing (run phase 2 first)"
                    if not is_transcript_done(temp_dir, video_file.stem)
                    else (
                        "title missing (run phase 3 first)"
                        if not is_title_done(temp_dir, video_file.stem)
                        else (
                            "title empty"
                            if not _title_text(video_file)
                            else None
                        )
                    )
                )
            ),
        ),
        # NEW: Phase 7 - Video Reconciliation (delete server video if local title differs)
        _PipelinePhase(
            7,
            "Video Reconciliation",
            lambda video_file, vi, vn: run_video_reconciliation_phase(
                video_path=video_file,
                video_index=vi,
                total_videos=vn,
                server_cache=server_cache,
                temp_dir=temp_dir,
            ),
            skip_reason=lambda video_file: (
                "media manager disabled"
                if server_cache is None
                else (
                    "title missing (run phase 3 first)"
                    if not is_title_done(temp_dir, video_file.stem)
                    else (
                        "title empty"
                        if not _title_text(video_file)
                        else (
                            "video not found on server"
                            if not _video_meta(video_file)
                            else (
                                "title unchanged"
                                if _video_meta(video_file).get("title", "").strip() == _title_text(video_file)
                                else None
                            )
                        )
                    )
                )
            ),
        ),
        # NEW: Phase 8 - Video Upload (with pending tags, handles trash re-upload)
        _PipelinePhase(
            8,
            "Video Upload",
            lambda video_file, vi, vn: run_video_upload_phase(
                video_path=video_file,
                output_dir=startup.output_dir,
                temp_dir=temp_dir,
                video_index=vi,
                total_videos=vn,
                server_cache=server_cache,
            ),
            skip_reason=lambda video_file: (
                "final encode not completed"
                if not is_completed(temp_dir, video_file.stem)
                else (
                    "title missing (run phase 3 first)"
                    if not is_title_done(temp_dir, video_file.stem)
                    else (
                        "media manager disabled"
                        if server_cache is None
                        else (
                            "title empty"
                            if not _title_text(video_file)
                            else (
                                "already published"
                                if (
                                    _video_meta(video_file)
                                    and (
                                        "FB" in _video_meta(video_file).get("tags", [])
                                        or "TT" in _video_meta(video_file).get("tags", [])
                                    )
                                )
                                else (
                                    "already pending"
                                    if (
                                        _video_meta(video_file)
                                        and "pending" in _video_meta(video_file).get("tags", [])
                                    )
                                    else (
                                        "video trashed on server"
                                        if _video_meta(video_file) and server_cache.is_video_trash(video_file.stem)
                                        else (
                                            "title mismatch; reconciliation required"
                                            if (
                                                _video_meta(video_file)
                                                and _video_meta(video_file).get("title", "").strip()
                                                != _title_text(video_file)
                                            )
                                            else None
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            ),
        ),
        # UPDATED: Phase 9 - Publish Video (was Phase 8)
        _PipelinePhase(
            9,
            "Publish Video",
            lambda video_file, vi, vn: run_video_tag_promotion_phase(
                video_path=video_file,
                output_dir=startup.output_dir,
                temp_dir=temp_dir,
                video_index=vi,
                total_videos=vn,
                server_cache=server_cache,
            ),
            skip_reason=lambda video_file: (
                "media manager disabled"
                if server_cache is None
                else (
                    "audio not ready"
                    if not server_cache.is_audio_ready(video_file.stem)
                    else (
                        "video not found on server"
                        if not _video_meta(video_file)
                        else (
                            "already published"
                            if (
                                "FB" in _video_meta(video_file).get("tags", [])
                                or "TT" in _video_meta(video_file).get("tags", [])
                            )
                            else None
                        )
                    )
                )
            ),
        ),
    )

    for phase in phases:
        _run_phase(videos=videos, phase=phase)
        # Rebuild cache after Phase 7 (reconciliation) and Phase 8 (upload)
        # so subsequent phases see fresh server state
        if media_manager_enabled and phase.index in (7, 8):
            server_cache = _rebuild_server_cache(os.getenv('MEDIA_MANAGER_URL') or '')

    return startup
