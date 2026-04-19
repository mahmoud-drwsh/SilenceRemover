"""Tests for silence_removed_runner progress routing."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

from src.ffmpeg import silence_removed_runner


def test_run_with_script_routes_progress_commands_without_duration(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, float | None]] = []

    monkeypatch.setattr(
        silence_removed_runner,
        "run_with_progress",
        lambda cmd, *, expected_total_seconds, on_progress=None, check=True: calls.append(
            ("progress", expected_total_seconds)
        ),
    )
    monkeypatch.setattr(
        silence_removed_runner,
        "run",
        lambda *args, **kwargs: calls.append(("run", None)),
    )
    monkeypatch.setattr(
        silence_removed_runner,
        "wait_for_file_release",
        lambda _path: None,
    )

    output_file = tmp_path / "out.mp4"
    result = silence_removed_runner.run_silence_removed_media_with_script(
        input_file=tmp_path / "input.mp4",
        output_file=output_file,
        filter_script_path=tmp_path / "graph.ffscript",
        build_command=lambda *_args: [
            "ffmpeg",
            "-i",
            "input.mp4",
            "-progress",
            "pipe:1",
            str(output_file),
        ],
    )

    assert result == output_file.resolve()
    assert calls == [("progress", 0.0)]


def test_run_with_script_uses_plain_run_without_progress_flag(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        silence_removed_runner,
        "run_with_progress",
        lambda *args, **kwargs: calls.append("progress"),
    )
    monkeypatch.setattr(
        silence_removed_runner,
        "run",
        lambda *args, **kwargs: calls.append("run"),
    )
    monkeypatch.setattr(
        silence_removed_runner,
        "wait_for_file_release",
        lambda _path: None,
    )

    output_file = tmp_path / "out.ogg"
    silence_removed_runner.run_silence_removed_media_with_script(
        input_file=tmp_path / "input.mp4",
        output_file=output_file,
        filter_script_path=tmp_path / "graph.ffscript",
        build_command=lambda *_args: ["ffmpeg", "-i", "input.mp4", str(output_file)],
    )

    assert calls == ["run"]
