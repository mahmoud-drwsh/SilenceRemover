"""Tests for FFmpeg runner progress output."""

from __future__ import annotations

import subprocess
import sys
from io import StringIO

import pytest

from src.ffmpeg import runner


class _FakeStdout(StringIO):
    def __init__(self, *, is_tty: bool) -> None:
        super().__init__()
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def test_parse_ffmpeg_progress_speed() -> None:
    assert runner._parse_ffmpeg_progress_speed("speed=0.82x") == "0.82x"
    assert runner._parse_ffmpeg_progress_speed("progress=continue") is None
    assert runner._parse_ffmpeg_progress_speed("speed=N/A") is None


def test_run_with_progress_prints_speed_only_and_newline(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePopen:
        def __init__(self, *args, **kwargs) -> None:
            self.stdout = StringIO(
                "frame=1326\n"
                "speed=N/A\n"
                "progress=continue\n"
                "speed=0.82x\n"
                "out_time=00:00:43.633333\n"
                "speed=0.95x\n"
                "progress=end\n"
            )
            self.returncode = 1

        def wait(self) -> int:
            return self.returncode

    stream = _FakeStdout(is_tty=True)
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(runner.subprocess, "Popen", FakePopen)

    with pytest.raises(subprocess.CalledProcessError):
        runner.run_with_progress(["ffmpeg"], expected_total_seconds=60.0)

    assert stream.getvalue() == "\r0.82x\033[K\r0.95x\033[K\n"


def test_run_with_progress_preserves_callback_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePopen:
        def __init__(self, *args, **kwargs) -> None:
            self.stdout = StringIO(
                "out_time_ms=1000000\n"
                "speed=0.82x\n"
                "out_time=00:00:01.500000\n"
                "out_time_ms=2500000\n"
                "progress=end\n"
            )
            self.returncode = 0

        def wait(self) -> int:
            return self.returncode

    stream = _FakeStdout(is_tty=False)
    updates: list[tuple[int, float]] = []

    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(runner.subprocess, "Popen", FakePopen)

    result = runner.run_with_progress(
        ["ffmpeg"],
        expected_total_seconds=10.0,
        on_progress=lambda percent, seconds: updates.append((percent, seconds)),
    )

    assert result.returncode == 0
    assert updates == [(10, 1.0), (15, 1.5), (25, 2.5)]
    assert stream.getvalue() == "\r0.82x\n"
