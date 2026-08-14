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


def test_remote_title_phase_writes_service_response_locally(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "horizontal.mkv"
    snippet = tmp_path / "temp" / "snippet" / "horizontal.ogg"
    snippet.parent.mkdir(parents=True)
    snippet.write_bytes(b"OggSsnippet")
    closed: list[bool] = []

    class FakeClient:
        def __init__(self, _url: str):
            pass

        def analyze_ogg_snippet(self, path: Path) -> tuple[str, str]:
            assert path == snippet
            return "النص المفرغ", "العنوان"

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(pipeline, "MediaManagerClient", FakeClient)
    monkeypatch.setattr(
        pipeline,
        "_run_phase_step",
        lambda *, video_path, work_fn, video_index, total_videos, label: work_fn() or True,
    )

    assert pipeline.run_remote_transcription_and_title_phase(video, tmp_path / "temp", 1, 1) is True
    assert (tmp_path / "temp" / "transcript" / "horizontal.txt").read_text(encoding="utf-8") == "النص المفرغ"
    assert (tmp_path / "temp" / "title" / "horizontal.txt").read_text(encoding="utf-8") == "العنوان"
    assert closed == [True]
