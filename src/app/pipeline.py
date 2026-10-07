"""Pipeline orchestration for SilenceRemover.

The pipeline makes one silence-removed output for each video: the no-overlay
video. It has no title banner, no logo and no subtitles.
"""

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
)
from src.core.paths import (
    get_completed_path,
    get_snippet_path,
    get_title_path,
    get_transcript_path,
    is_completed,
    is_snippet_done,
    is_title_done,
    is_transcript_done,
    mark_completed,
)
from sr_filename import sanitize_filename
from src.startup import StartupContext, build_startup_context

from sr_snippet import create_silence_removed_snippet
from sr_telegram_notify import (
    notify_final_encoding_started,
    notify_final_output_ready,
)
from sr_title import generate_title_from_transcript
from sr_transcription import transcribe_and_save
from src.ffmpeg.trim_script_bundle import (
    generate_trim_script,
    get_snippet_trim_script_path,
    get_trim_script_path,
    is_trim_script_ready,
)
from src.media.trim import trim_single_video

# Optional Media Manager integration for title sync and upload (Phases 3 and 5)
try:
    from sr_media_manager import MediaManagerClient
    _MEDIA_MANAGER_AVAILABLE = True
except ImportError:
    _MEDIA_MANAGER_AVAILABLE = False

@dataclass(frozen=True)
class _PipelinePhase:
    index: int
    label: str
    run: Callable[[Path, int, int], bool | None]
    skip_reason: Callable[[Path], str | None] | None = None
    checked_paths: Callable[[Path], list[str]] | None = None


class _ConsolePhaseProgress:
    """Plain line-by-line phase progress output."""

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self._is_tty = bool(getattr(stream, "isatty", lambda: False)())
        self._current_phase: str | None = None
        self._live_line_open = False

    def start_phase(self, label: str) -> None:
        if self._current_phase == label:
            return
        self.finish_line()
        self.stream.write("\n")
        self.stream.flush()
        self._current_phase = label

    def show_file_progress(self, label: str, video_index: int, total_videos: int, name: str) -> None:
        self.start_phase(label)
        self.finish_line()
        message = f"[{label}] File {video_index}/{total_videos}: {name}"
        self.stream.write(f"{message}\n")
        self.stream.flush()

    def show_skip_summary(self, label: str, skipped: int, total_videos: int) -> None:
        self.finish_line()
        self.stream.write(f"[{label}] Skipped {skipped}/{total_videos}\n")
        self.stream.flush()

    def show_upload_progress(
        self,
        label: str,
        video_index: int,
        total_videos: int,
        name: str,
        uploaded_bytes: int,
        total_bytes: int,
    ) -> None:
        if not self._is_tty or total_bytes <= 0:
            return

        self.start_phase(label)
        transferred = min(max(uploaded_bytes, 0), total_bytes)
        percent = int(min(100.0, max(0.0, (transferred / total_bytes) * 100.0)))
        transferred_mib = transferred / (1024 * 1024)
        total_mib = total_bytes / (1024 * 1024)
        message = (
            f"[{label}] Upload {video_index}/{total_videos}: {name} | "
            f"{percent}% | {transferred_mib:.2f}/{total_mib:.2f} MiB"
        )
        self.stream.write(f"\r{message}\033[K")
        self.stream.flush()
        self._live_line_open = True

    def show_failure(self, name: str, reason: str) -> None:
        self.finish_line()
        self.stream.write(f"  failed: {name} ({reason})\n")
        self.stream.flush()

    def show_check(self, name: str, paths: list[str]) -> None:
        self.finish_line()
        if paths:
            checked = " | ".join(paths)
        else:
            checked = "(no path)"
        self.stream.write(f"  check: {name} -> {checked}\n")
        self.stream.flush()

    def finish_line(self) -> None:
        if not self._live_line_open:
            return
        self.stream.write("\n")
        self.stream.flush()
        self._live_line_open = False


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
    decisions = [
        (i, video_file, phase.skip_reason(video_file) if phase.skip_reason is not None else None)
        for i, video_file in enumerate(videos, 1)
    ]
    runnable = [(i, video_file) for i, video_file, reason in decisions if not reason]
    skip_count = n - len(runnable)

    phase_progress = _get_phase_progress()
    phase_progress.start_phase(phase.label)
    if skip_count:
        phase_progress.show_skip_summary(phase.label, skip_count, n)

    for i, video_file in runnable:
        if phase.checked_paths is not None:
            phase_progress.show_check(video_file.name, phase.checked_paths(video_file))
        try:
            result = phase.run(video_file, i, n)
        except Exception as err:
            fail_count += 1
            reason = str(err).strip() or err.__class__.__name__
            phase_progress.show_failure(video_file.name, reason)
            continue
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
    phase_progress = _get_phase_progress()
    phase_progress.finish_line()
    stream = phase_progress.stream
    stream.write(f"  processing: {video_path.name}\n")
    stream.flush()
    phase_progress.show_file_progress(label, video_index, total_videos, video_path.name)

    try:
        work_fn()
        return True
    except Exception as err:
        phase_progress.finish_line()
        reason = str(err).strip() or err.__class__.__name__
        phase_progress.show_failure(video_path.name, reason)
        return False


def _build_upload_progress_callback(
    *,
    label: str,
    video_path: Path,
    video_index: int,
    total_videos: int,
) -> Callable[[int, int], None]:
    phase_progress = _get_phase_progress()

    def _on_progress(uploaded_bytes: int, total_bytes: int) -> None:
        phase_progress.show_upload_progress(
            label,
            video_index,
            total_videos,
            video_path.name,
            uploaded_bytes,
            total_bytes,
        )

    return _on_progress


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
    trim_script_path: Path,
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
            trim_script_path=trim_script_path,
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


def run_remote_transcription_and_title_phase(
    video_path: Path,
    temp_dir: Path,
    video_index: int,
    total_videos: int,
) -> bool | None:
    """Use Media Manager's server-held OpenRouter key for a local review snippet."""
    basename = video_path.stem
    snippet_path = get_snippet_path(temp_dir, basename)
    transcript_path = get_transcript_path(temp_dir, basename)
    title_path = get_title_path(temp_dir, basename)

    def _perform() -> None:
        client = MediaManagerClient(os.getenv("MEDIA_MANAGER_URL"))
        try:
            transcript, title = client.analyze_ogg_snippet(snippet_path)
        finally:
            client.close()
        transcript = transcript.strip()
        title = title.strip()
        if not transcript or not title:
            raise RuntimeError("Media Manager returned an empty transcript or title")
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        title_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(transcript, encoding="utf-8")
        title_path.write_text(title, encoding="utf-8")

    return _run_phase_step(
        video_path=video_path,
        work_fn=_perform,
        video_index=video_index,
        total_videos=total_videos,
        label="Server Transcription and Title",
    )


@dataclass(frozen=True)
class ServerDataCache:
    """Server originals fetched once at pipeline start."""
    original_files: dict[str, dict]

    def has_original(self, file_id: str) -> bool:
        return file_id in self.original_files


def run_original_upload_phase(
    video_path: Path,
    video_index: int,
    total_videos: int,
) -> bool | None:
    """Upload the immutable source recording before any derived artifact."""
    def _perform() -> None:
        client = MediaManagerClient(os.getenv("MEDIA_MANAGER_URL"))
        try:
            if not client.upload_original(
                video_path.stem,
                video_path,
                progress_callback=_build_upload_progress_callback(
                    label="Original Upload",
                    video_path=video_path,
                    video_index=video_index,
                    total_videos=total_videos,
                ),
            ):
                raise RuntimeError("Original upload did not complete")
        finally:
            client.close()

    return _run_phase_step(
        video_path=video_path,
        work_fn=_perform,
        video_index=video_index,
        total_videos=total_videos,
        label="Original Upload",
    )


def original_upload_skip_reason(
    video_path: Path,
    server_cache: ServerDataCache | None,
) -> str | None:
    if server_cache is None:
        return "media manager disabled"
    if server_cache.has_original(video_path.stem):
        return "original already exists on server"
    return None


def run_encode_phase(
    video_path: Path,
    output_dir: Path,
    temp_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
    trim_script_path: Path,
    encoder: str,
    video_index: int = 1,
    total_videos: int = 1,
) -> bool | None:
    """Phase 8: Encode the no-overlay video with a title-based output filename.

    This is the only encode. The output has no title banner, no logo and no
    subtitles. The title goes into the container metadata.
    """
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
            temp_dir=temp_dir,
            metadata_title=clean_title,
            trim_script_path=trim_script_path,
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


def run_trim_script_generation_phase(
    video_path: Path,
    temp_dir: Path,
    target_length: Optional[float],
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    video_index: int,
    total_videos: int,
) -> bool | None:
    """Phase 0: Generate reusable final and snippet trim scripts."""

    def _perform() -> None:
        generate_trim_script(
            input_file=video_path,
            temp_dir=temp_dir,
            target_length=target_length,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
        )

    return _run_phase_step(
        video_path=video_path,
        work_fn=_perform,
        video_index=video_index,
        total_videos=total_videos,
        label="Trim Script Generation",
    )


def _rebuild_server_cache(media_manager_url: str) -> ServerDataCache | None:
    """Fetch the server originals once. Return None when the server is not available."""
    try:
        client = MediaManagerClient(media_manager_url)
        try:
            original_files = {
                original_id: original
                for original in client.get_original_files()
                if (original_id := original.get('id'))
            }
            return ServerDataCache(original_files=original_files)
        finally:
            client.close()
    except Exception:
        return None


def run(args: argparse.Namespace | None = None) -> StartupContext:
    """Run the media processing pipeline."""
    if args is None:
        args = parse_args()
    startup = build_startup_context(args)
    api_key = startup.api_key
    temp_dir = startup.temp_dir
    videos = startup.videos

    # A configured Media Manager owns processing by default. The client only
    # uploads immutable Originals; it never needs an opt-in processing flag.
    media_manager_enabled = bool(_MEDIA_MANAGER_AVAILABLE and os.getenv('MEDIA_MANAGER_URL'))
    local_title_and_trim_only = bool(getattr(args, "local_title_and_trim_only", False))
    if media_manager_enabled and not local_title_and_trim_only:
        server_cache = _rebuild_server_cache(os.getenv('MEDIA_MANAGER_URL') or '')
        upload_phase = _PipelinePhase(
            0,
            "Original Upload",
            lambda video_file, vi, vn: run_original_upload_phase(
                video_path=video_file, video_index=vi, total_videos=vn,
            ),
            skip_reason=lambda video_file: original_upload_skip_reason(video_file, server_cache),
            checked_paths=lambda video_file: [f"server:original/{video_file.stem}"],
        )
        _run_phase(videos=videos, phase=upload_phase)
        return startup

    # Without the Media Manager upload path, all phases are local. A horizontal
    # run with a configured Media Manager uses the service only for the
    # transient title request. The PC uploads no derived artifact.
    remote_title_service_enabled = media_manager_enabled and local_title_and_trim_only

    if not videos:
        return startup

    def _title_text(video_file: Path) -> str:
        title_path = get_title_path(temp_dir, video_file.stem)
        if not title_path.exists():
            return ""
        return title_path.read_text(encoding="utf-8").strip()

    def _trim_script_path(video_file: Path) -> Path:
        return get_trim_script_path(
            input_file=video_file,
            temp_dir=temp_dir,
            target_length=startup.target_length,
            noise_threshold=startup.noise_threshold,
            min_duration=startup.min_duration,
            pad_sec=startup.pad_sec,
        )

    def _snippet_trim_script_path(video_file: Path) -> Path:
        return get_snippet_trim_script_path(
            input_file=video_file,
            temp_dir=temp_dir,
            target_length=startup.target_length,
            noise_threshold=startup.noise_threshold,
            min_duration=startup.min_duration,
            pad_sec=startup.pad_sec,
        )

    phases = (
        _PipelinePhase(
            0,
            "Trim Script Generation",
            lambda video_file, vi, vn: run_trim_script_generation_phase(
                video_path=video_file,
                temp_dir=temp_dir,
                target_length=startup.target_length,
                noise_threshold=startup.noise_threshold,
                min_duration=startup.min_duration,
                pad_sec=startup.pad_sec,
                video_index=vi,
                total_videos=vn,
            ),
            skip_reason=lambda video_file: (
                "trim script already generated"
                if is_trim_script_ready(
                    input_file=video_file,
                    temp_dir=temp_dir,
                    target_length=startup.target_length,
                    noise_threshold=startup.noise_threshold,
                    min_duration=startup.min_duration,
                    pad_sec=startup.pad_sec,
                )
                else None
            ),
            checked_paths=lambda video_file: [
                str(_trim_script_path(video_file)),
                str(_snippet_trim_script_path(video_file)),
            ],
        ),
        # NEW: Phase 1 - Snippet Creation
        _PipelinePhase(
            1,
            "Snippet Creation",
            lambda video_file, vi, vn: run_snippet_phase(
                video_path=video_file,
                temp_dir=temp_dir,
                trim_script_path=_trim_script_path(video_file),
                pad_sec=startup.pad_sec,
                video_index=vi,
                total_videos=vn,
            ),
            skip_reason=lambda video_file: ("snippet already exists"
                if is_snippet_done(temp_dir, video_file.stem)
                else ("trim script missing (run phase 0 first)"
                    if not is_trim_script_ready(
                        input_file=video_file,
                        temp_dir=temp_dir,
                        target_length=startup.target_length,
                        noise_threshold=startup.noise_threshold,
                        min_duration=startup.min_duration,
                        pad_sec=startup.pad_sec,
                    )
                    else None)
            ),
            checked_paths=lambda video_file: [
                str(get_snippet_path(temp_dir, video_file.stem)),
                str(_trim_script_path(video_file)),
                str(_snippet_trim_script_path(video_file)),
            ],
        ),
        # UPDATED: Phase 2 - Transcription (was Phase 1)
        _PipelinePhase(
            2,
            "Transcription",
            lambda video_file, vi, vn: (
                run_remote_transcription_and_title_phase(
                    video_path=video_file,
                    temp_dir=temp_dir,
                    video_index=vi,
                    total_videos=vn,
                )
                if remote_title_service_enabled
                else run_transcription_phase(
                    video_path=video_file,
                    temp_dir=temp_dir,
                    pad_sec=startup.pad_sec,
                    api_key=api_key,
                    video_index=vi,
                    total_videos=vn,
                )
            ),
            skip_reason=lambda video_file: (
                "transcript already exists"
                if is_transcript_done(temp_dir, video_file.stem)
                else (
                    "snippet missing or empty (run phase 1 first)"
                    if not is_snippet_done(temp_dir, video_file.stem)
                    else None
                )
            ),
            checked_paths=lambda video_file: [
                str(get_snippet_path(temp_dir, video_file.stem)),
                str(get_transcript_path(temp_dir, video_file.stem)),
            ],
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
                else None
            ),
            checked_paths=lambda video_file: [
                str(get_title_path(temp_dir, video_file.stem)),
            ],
        ),
        # Phase 8 - Final Encode: the one encode. It makes the no-overlay video.
        _PipelinePhase(
            8,
            "Final Encode",
            lambda video_file, vi, vn: run_encode_phase(
                video_path=video_file,
                output_dir=startup.output_dir,
                temp_dir=startup.temp_dir,
                noise_threshold=startup.noise_threshold,
                min_duration=startup.min_duration,
                pad_sec=startup.pad_sec,
                target_length=startup.target_length,
                trim_script_path=_trim_script_path(video_file),
                encoder=args.encoder,
                video_index=vi,
                total_videos=vn,
            ),
            skip_reason=lambda video_file: ("already completed"
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
                            else (
                                "trim script missing (run phase 0 first)"
                                if not is_trim_script_ready(
                                    input_file=video_file,
                                    temp_dir=temp_dir,
                                    target_length=startup.target_length,
                                    noise_threshold=startup.noise_threshold,
                                    min_duration=startup.min_duration,
                                    pad_sec=startup.pad_sec,
                                )
                                else None
                            )
                        )
                    )
                )
            ),
            checked_paths=lambda video_file: [
                str(get_completed_path(temp_dir, video_file.stem)),
                str(get_transcript_path(temp_dir, video_file.stem)),
                str(get_title_path(temp_dir, video_file.stem)),
                str(_trim_script_path(video_file)),
                str(_snippet_trim_script_path(video_file)),
            ],
        ),
    )

    for phase in phases:
        _run_phase(videos=videos, phase=phase)

    return startup
