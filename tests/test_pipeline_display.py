"""Tests for TTY-aware pipeline phase progress output."""

from __future__ import annotations

import os
import sys
from io import StringIO
from pathlib import Path

from src.app import pipeline


class _FakeStream(StringIO):
    def __init__(self, *, is_tty: bool) -> None:
        super().__init__()
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def test_tty_progress_uses_current_newline_format() -> None:
    stream = _FakeStream(is_tty=True)
    progress = pipeline._ConsolePhaseProgress(stream)

    progress.start_phase("Snippet Creation")
    progress.show_file_progress("Snippet Creation", 1, 2, "a.mkv")
    progress.show_file_progress("Snippet Creation", 2, 2, "b.mkv")
    progress.finish_line()

    assert stream.getvalue() == (
        "\n"
        "[Snippet Creation] File 1/2: a.mkv\n"
        "[Snippet Creation] File 2/2: b.mkv\n"
    )


def test_non_tty_progress_falls_back_to_newlines() -> None:
    stream = _FakeStream(is_tty=False)
    progress = pipeline._ConsolePhaseProgress(stream)

    progress.start_phase("Transcription")
    progress.show_file_progress("Transcription", 1, 2, "a.mkv")
    progress.show_file_progress("Transcription", 2, 2, "b.mkv")
    progress.finish_line()

    assert stream.getvalue() == (
        "\n"
        "[Transcription] File 1/2: a.mkv\n"
        "[Transcription] File 2/2: b.mkv\n"
    )


def test_phase_change_inserts_blank_line_after_tty_progress() -> None:
    stream = _FakeStream(is_tty=True)
    progress = pipeline._ConsolePhaseProgress(stream)

    progress.show_file_progress("Title Generation", 1, 1, "first.mkv")
    progress.show_file_progress("Overlay Generation", 1, 1, "second.mkv")
    progress.finish_line()

    assert "\n[Title Generation] File 1/1: first.mkv\n\n[Overlay Generation] File 1/1: second.mkv\n" == stream.getvalue()


def test_tty_skip_progress_reuses_one_live_line() -> None:
    stream = _FakeStream(is_tty=True)
    progress = pipeline._ConsolePhaseProgress(stream)

    progress.start_phase("Transcription")
    progress.show_skip("Transcription", 1, 3, "a.mkv", "transcript already exists", 1)
    progress.show_skip("Transcription", 2, 3, "b.mkv", "transcript already exists", 2)
    progress.finish_line()

    assert stream.getvalue() == (
        "\n"
        "\r[Transcription] Skip 1/3: a.mkv\033[K"
        "\r[Transcription] Skip 2/3: b.mkv\033[K\n"
    )


def test_tty_skip_progress_truncates_long_names_to_terminal_width(monkeypatch) -> None:
    stream = _FakeStream(is_tty=True)
    progress = pipeline._ConsolePhaseProgress(stream)
    monkeypatch.setattr(pipeline.shutil, "get_terminal_size", lambda fallback=(80, 24): os.terminal_size((50, 24)))

    progress.start_phase("Title Overlay Generation")
    progress.show_skip(
        "Title Overlay Generation",
        1,
        5,
        "2026-03-27 14-11-22-vertical.mkv",
        "title overlay already generated for current title",
        1,
    )
    progress.finish_line()

    assert stream.getvalue() == (
        "\n"
        "\r[Title Overlay Generation] Skip 1/5: 2026-03-27...\033[K\n"
    )
    rendered_line = stream.getvalue().split("\r", 1)[1].split("\033[K", 1)[0]
    assert len(rendered_line) <= 50


def test_tty_upload_progress_reuses_one_live_line() -> None:
    stream = _FakeStream(is_tty=True)
    progress = pipeline._ConsolePhaseProgress(stream)

    progress.show_upload_progress("Audio Upload", 1, 2, "clip.mkv", 1048576, 4194304)
    progress.show_upload_progress("Audio Upload", 1, 2, "clip.mkv", 2097152, 4194304)
    progress.finish_line()

    assert stream.getvalue() == (
        "\n"
        "\r[Audio Upload] Upload 1/2: clip.mkv | 25% | 1.00/4.00 MiB\033[K"
        "\r[Audio Upload] Upload 1/2: clip.mkv | 50% | 2.00/4.00 MiB\033[K\n"
    )


def test_run_phase_skips_do_not_emit_check_lines_and_flush_before_next_output(monkeypatch) -> None:
    stream = _FakeStream(is_tty=True)
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(pipeline, "_PHASE_PROGRESS", None)

    phase = pipeline._PipelinePhase(
        index=2,
        label="Transcription",
        run=lambda video_file, vi, vn: True,
        skip_reason=lambda video_file: "transcript already exists" if video_file.name == "a.mkv" else None,
        checked_paths=lambda video_file: [f"/tmp/{video_file.name}"],
    )

    result = pipeline._run_phase([Path("a.mkv"), Path("b.mkv")], phase)

    assert result == (1, 1, 0)
    output = stream.getvalue()
    assert "check: a.mkv" not in output
    assert "\033[K\n  check: b.mkv -> /tmp/b.mkv\n" in output


def test_upload_progress_flushes_before_next_output() -> None:
    stream = _FakeStream(is_tty=True)
    progress = pipeline._ConsolePhaseProgress(stream)

    progress.show_upload_progress("Video Upload", 2, 5, "clip.mkv", 1048576, 2097152)
    progress.show_check("clip.mkv", ["/tmp/out.mp4"])

    assert stream.getvalue() == (
        "\n"
        "\r[Video Upload] Upload 2/5: clip.mkv | 50% | 1.00/2.00 MiB\033[K\n"
        "  check: clip.mkv -> /tmp/out.mp4\n"
    )


def test_non_tty_skips_use_concise_newline_summaries(monkeypatch) -> None:
    stream = _FakeStream(is_tty=False)
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(pipeline, "_PHASE_PROGRESS", None)

    phase = pipeline._PipelinePhase(
        index=1,
        label="Snippet Creation",
        run=lambda video_file, vi, vn: True,
        skip_reason=lambda video_file: "snippet already exists",
        checked_paths=lambda video_file: [f"/tmp/{video_file.name}"],
    )

    result = pipeline._run_phase([Path("a.mkv"), Path("b.mkv")], phase)

    assert result == (0, 2, 0)
    assert stream.getvalue() == (
        "\n"
        "  skip: a.mkv (snippet already exists)\n"
        "  skip: b.mkv (snippet already exists)\n"
    )


def test_run_phase_step_reports_failure_with_current_output(monkeypatch) -> None:
    stream = _FakeStream(is_tty=True)
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(pipeline, "_PHASE_PROGRESS", None)

    result = pipeline._run_phase_step(
        video_path=Path("broken.mkv"),
        work_fn=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        video_index=1,
        total_videos=3,
        label="Snippet Creation",
    )

    stream.write("Traceback line 1\nTraceback line 2\n")

    assert result is False
    assert (
        "  processing: broken.mkv\n"
        "\n"
        "[Snippet Creation] File 1/3: broken.mkv\n"
        "  failed: broken.mkv (boom)\n"
        "Traceback line 1\nTraceback line 2\n"
    ) == stream.getvalue()
