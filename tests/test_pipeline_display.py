"""Tests for TTY-aware pipeline phase progress output."""

from __future__ import annotations

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


def test_tty_progress_rewrites_single_line() -> None:
    stream = _FakeStream(is_tty=True)
    progress = pipeline._ConsolePhaseProgress(stream)

    progress.start_phase("Snippet Creation")
    progress.show_file_progress("Snippet Creation", 1, 2, "a.mkv")
    progress.show_file_progress("Snippet Creation", 2, 2, "b.mkv")
    progress.finish_line()

    assert stream.getvalue() == (
        "\n"
        "\r[Snippet Creation] File 1/2: a.mkv\033[K"
        "\r[Snippet Creation] File 2/2: b.mkv\033[K\n"
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

    assert "\033[K\n\n\r[Overlay Generation] File 1/1: second.mkv\033[K\n" in stream.getvalue()


def test_run_phase_step_flushes_tty_line_before_error_output(monkeypatch) -> None:
    stream = _FakeStream(is_tty=True)
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(pipeline, "_PHASE_PROGRESS", None)

    result = pipeline._run_phase_step(
        video_path=Path("broken.mkv"),
        already_done=False,
        already_done_message="",
        work_fn=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        success_message="",
        failure_label="Phase 1",
        phase_index=1,
        total_phases=9,
        video_index=1,
        total_videos=3,
        label="Snippet Creation",
    )

    stream.write("Traceback line 1\nTraceback line 2\n")

    assert result is False
    assert "\033[K\nTraceback line 1\nTraceback line 2\n" in stream.getvalue()
