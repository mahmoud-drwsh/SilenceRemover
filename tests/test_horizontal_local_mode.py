"""Horizontal local mode keeps only title generation and one final encode."""

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

from src.app import pipeline


def test_local_title_and_trim_only_runs_no_subtitle_overlay_or_upload_phases(monkeypatch, tmp_path: Path) -> None:
    startup = SimpleNamespace(
        api_key="test-key",
        temp_dir=tmp_path / "temp",
        videos=[tmp_path / "horizontal.mkv"],
        target_length=None,
        noise_threshold=-40.0,
        min_duration=1.0,
        pad_sec=0.5,
        output_dir=tmp_path / "output",
        title_font="Noto Naskh Arabic",
        enable_title_overlay=False,
        enable_logo_overlay=False,
    )
    phase_indexes: list[int] = []

    monkeypatch.setattr(pipeline, "build_startup_context", lambda _args: startup)
    monkeypatch.setattr(pipeline, "_MEDIA_MANAGER_AVAILABLE", False)
    monkeypatch.setattr(
        pipeline,
        "_run_phase",
        lambda *, videos, phase: phase_indexes.append(phase.index),
    )

    pipeline.run(
        Namespace(
            local_title_and_trim_only=True,
            encoder="X265",
            title_y_fraction=None,
            title_height_fraction=None,
        )
    )

    assert phase_indexes == [0, 1, 2, 3, 8]
