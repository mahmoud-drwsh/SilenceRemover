"""Tests for upload phase notifications and progress wiring."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app import pipeline


def test_run_audio_upload_phase_wires_progress_and_notifies_on_success(
    monkeypatch,
    tmp_path: Path,
) -> None:
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()

    video_path = tmp_path / "clip.mkv"
    video_path.write_text("video")
    (temp_dir / "title").mkdir()
    (temp_dir / "snippet").mkdir()
    (temp_dir / "title" / "clip.txt").write_text("My Title", encoding="utf-8")
    (temp_dir / "snippet" / "clip.ogg").write_text("ogg", encoding="utf-8")

    upload_calls: list[tuple[str, str, Path]] = []
    notify_calls: list[tuple[int, int, str, str]] = []

    class FakeClient:
        def upload_audio(self, file_id, title, snippet_path, tags, progress_callback, source_id=None):
            upload_calls.append((file_id, title, snippet_path))
            assert tags == ["todo"]
            assert source_id == "clip"
            assert callable(progress_callback)
            progress_callback(512, 1024)
            return True

        def close(self):
            return None

    monkeypatch.setattr(pipeline, "MediaManagerClient", lambda _url: FakeClient())
    monkeypatch.setattr(
        pipeline,
        "notify_audio_uploaded",
        lambda *, video_index, total_videos, input_name, title: notify_calls.append(
            (video_index, total_videos, input_name, title)
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_run_phase_step",
        lambda *, video_path, work_fn, video_index, total_videos, label: work_fn() or True,
    )

    result = pipeline.run_audio_upload_phase(
        video_path=video_path,
        temp_dir=temp_dir,
        video_index=2,
        total_videos=5,
        server_cache=None,
    )

    assert result is True
    assert upload_calls == [("clip", "My Title", temp_dir / "snippet" / "clip.ogg")]
    assert notify_calls == [(2, 5, "clip.mkv", "My Title")]


def test_run_original_upload_phase_uses_source_id_and_never_calls_llm(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """The source is delivered before derived uploads without external LLM calls."""
    video_path = tmp_path / "clip.mkv"
    video_path.write_bytes(b"source video")
    calls: list[tuple[str, Path]] = []

    class FakeClient:
        def upload_original(self, source_id, original_path, progress_callback):
            calls.append((source_id, original_path))
            assert callable(progress_callback)
            progress_callback(4, 12)
            return True

        def close(self):
            return None

    monkeypatch.setattr(pipeline, "MediaManagerClient", lambda _url: FakeClient())
    monkeypatch.setattr(
        pipeline,
        "transcribe_and_save",
        lambda **_kwargs: pytest.fail("original upload must not call transcription"),
    )
    monkeypatch.setattr(
        pipeline,
        "generate_title_from_transcript",
        lambda **_kwargs: pytest.fail("original upload must not call title generation"),
    )
    monkeypatch.setattr(
        pipeline,
        "_run_phase_step",
        lambda *, video_path, work_fn, video_index, total_videos, label: work_fn() or True,
    )

    assert pipeline.run_original_upload_phase(video_path, 1, 1) is True
    assert calls == [("clip", video_path)]


def test_original_upload_skip_reason_uses_the_startup_server_cache(tmp_path: Path) -> None:
    video_path = tmp_path / "clip.mkv"
    cache = pipeline.ServerDataCache(
        audio_files={},
        video_files={},
        original_files={"clip": {"id": "clip"}},
        audio_trash_ids=frozenset(),
        video_trash_ids=frozenset(),
        ready_audio_ids=frozenset(),
    )

    assert pipeline.original_upload_skip_reason(video_path, cache) == "original already exists on server"
    assert pipeline.original_upload_skip_reason(tmp_path / "missing.mkv", cache) is None


def test_server_cache_finds_the_no_overlay_video_by_its_id() -> None:
    cache = pipeline.ServerDataCache(
        audio_files={},
        video_files={"clip-no-overlay": {"id": "clip-no-overlay"}},
        original_files={},
        audio_trash_ids=frozenset(),
        video_trash_ids=frozenset(),
        ready_audio_ids=frozenset(),
    )

    assert cache.get_no_overlay_video("clip") == {"id": "clip-no-overlay"}
    assert cache.get_no_overlay_video("missing") is None


def _seed_title_and_completion(tmp_path: Path) -> tuple[Path, Path, Path]:
    temp_dir = tmp_path / "temp"
    output_dir = tmp_path / "output"
    temp_dir.mkdir()
    output_dir.mkdir()
    video_path = tmp_path / "clip.mkv"
    video_path.write_text("video")
    (temp_dir / "title").mkdir()
    (temp_dir / "completed").mkdir()
    (temp_dir / "title" / "clip.txt").write_text("My Title", encoding="utf-8")
    (temp_dir / "completed" / "clip.txt").write_text("final-name", encoding="utf-8")
    (output_dir / "final-name.mp4").write_text("mp4", encoding="utf-8")
    return video_path, temp_dir, output_dir


def test_encode_phase_makes_one_no_overlay_video_with_the_metadata_title(
    monkeypatch, tmp_path: Path,
) -> None:
    temp_dir = tmp_path / "temp"
    output_dir = tmp_path / "output"
    (temp_dir / "title").mkdir(parents=True)
    (temp_dir / "title" / "clip.txt").write_text("My Title", encoding="utf-8")
    video_path = tmp_path / "clip.mkv"
    video_path.write_text("video")
    encode_calls: list[dict] = []

    monkeypatch.setattr(pipeline, "trim_single_video", lambda **kwargs: encode_calls.append(kwargs))
    monkeypatch.setattr(pipeline, "notify_final_encoding_started", lambda **_kwargs: None)
    monkeypatch.setattr(pipeline, "notify_final_output_ready", lambda **_kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "_run_phase_step",
        lambda *, video_path, work_fn, video_index, total_videos, label: work_fn() or True,
    )

    assert pipeline.run_encode_phase(
        video_path=video_path,
        output_dir=output_dir,
        temp_dir=temp_dir,
        noise_threshold=-40.0,
        min_duration=0.2,
        pad_sec=0.1,
        target_length=178.0,
        trim_script_path=temp_dir / "trim.ffscript",
        encoder="libx265",
    ) is True
    assert encode_calls == [{
        "input_file": video_path,
        "output_dir": output_dir,
        "noise_threshold": -40.0,
        "min_duration": 0.2,
        "pad_sec": 0.1,
        "target_length": 178.0,
        "output_basename": "My Title",
        "encoder": "libx265",
        "temp_dir": temp_dir,
        "metadata_title": "My Title",
        "trim_script_path": temp_dir / "trim.ffscript",
    }]
    assert (temp_dir / "completed" / "clip.txt").read_text(encoding="utf-8") == "My Title"


def test_no_overlay_upload_phase_uploads_the_one_encoded_video_and_notifies(
    monkeypatch, tmp_path: Path,
) -> None:
    video_path, temp_dir, output_dir = _seed_title_and_completion(tmp_path)
    upload_calls: list[tuple[str, str, Path, list[str], str]] = []
    notify_calls: list[tuple[int, int, str, str]] = []

    class FakeClient:
        def upload_video(self, file_id, title, output_path, tags, progress_callback, skip_if_exists_with_title, source_id=None, **attributes):
            assert attributes == {
                "media_variant": "no-overlay",
                "visibility": "active",
                "publication_status": "published",
            }
            assert callable(progress_callback)
            assert skip_if_exists_with_title is True
            progress_callback(512, 1024)
            upload_calls.append((file_id, title, output_path, tags, source_id))
            return {"success": True, "uploaded": True, "skipped": False, "overwritten": False}

        def close(self):
            return None

    monkeypatch.setattr(pipeline, "MediaManagerClient", lambda _url: FakeClient())
    monkeypatch.setattr(
        pipeline,
        "notify_video_uploaded",
        lambda *, video_index, total_videos, input_name, title: notify_calls.append(
            (video_index, total_videos, input_name, title)
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_run_phase_step",
        lambda *, video_path, work_fn, video_index, total_videos, label: work_fn() or True,
    )

    assert pipeline.run_no_overlay_video_upload_phase(
        video_path=video_path, output_dir=output_dir, temp_dir=temp_dir, video_index=2, total_videos=5,
    ) is True
    assert upload_calls == [("clip-no-overlay", "My Title", output_dir / "final-name.mp4", [], "clip")]
    assert notify_calls == [(2, 5, "clip.mkv", "My Title")]


def test_no_overlay_upload_phase_skips_notification_on_non_uploaded_result(
    monkeypatch, tmp_path: Path,
) -> None:
    video_path, temp_dir, output_dir = _seed_title_and_completion(tmp_path)
    notify_calls: list[str] = []

    class FakeClient:
        def upload_video(self, *_args, **_kwargs):
            return {"success": True, "uploaded": False, "skipped": True, "overwritten": False}

        def close(self):
            return None

    monkeypatch.setattr(pipeline, "MediaManagerClient", lambda _url: FakeClient())
    monkeypatch.setattr(pipeline, "notify_video_uploaded", lambda **kwargs: notify_calls.append(kwargs["title"]))
    monkeypatch.setattr(
        pipeline,
        "_run_phase_step",
        lambda *, video_path, work_fn, video_index, total_videos, label: work_fn() or True,
    )

    assert pipeline.run_no_overlay_video_upload_phase(
        video_path=video_path, output_dir=output_dir, temp_dir=temp_dir, video_index=1, total_videos=1,
    ) is True
    assert notify_calls == []


def _startup(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        api_key="test-key",
        temp_dir=tmp_path / "temp",
        videos=[tmp_path / "clip.mkv"],
        target_length=None,
        noise_threshold=-40.0,
        min_duration=1.0,
        pad_sec=0.5,
        output_dir=tmp_path / "output",
    )


def test_local_pipeline_has_one_encode_and_no_subtitle_overlay_or_logo_phase(
    monkeypatch, tmp_path: Path,
) -> None:
    labels: list[str] = []
    monkeypatch.setattr(pipeline, "build_startup_context", lambda _args: _startup(tmp_path))
    monkeypatch.setattr(pipeline, "_MEDIA_MANAGER_AVAILABLE", False)
    monkeypatch.setattr(pipeline, "_run_phase", lambda *, videos, phase: labels.append(phase.label))

    pipeline.run(Namespace(local_title_and_trim_only=False, encoder="X265"))

    assert labels == [
        "Trim Script Generation", "Snippet Creation", "Transcription", "Title Generation",
        "Original Upload", "Audio Upload", "Final Encode", "No-Overlay Upload",
    ]


def test_server_owned_pipeline_uploads_the_original_without_logo_or_subtitle_calls(
    monkeypatch, tmp_path: Path,
) -> None:
    calls: list[str] = []

    class FakeClient:
        def __init__(self, _url: str) -> None:
            pass

        def __getattr__(self, name: str):
            def method(*_args, **_kwargs):
                calls.append(name)
                return True if name == "upload_original" else []
            return method

    monkeypatch.setattr(pipeline, "build_startup_context", lambda _args: _startup(tmp_path))
    monkeypatch.setattr(pipeline, "_MEDIA_MANAGER_AVAILABLE", True)
    monkeypatch.setattr(pipeline, "MediaManagerClient", FakeClient)
    monkeypatch.setenv("MEDIA_MANAGER_URL", "https://example.test/projects/token/project/")
    monkeypatch.setattr(
        pipeline,
        "_run_phase_step",
        lambda *, video_path, work_fn, video_index, total_videos, label: work_fn() or True,
    )

    pipeline.run(Namespace(local_title_and_trim_only=False, encoder="X265"))

    assert "upload_original" in calls
    assert not [name for name in calls if "logo" in name or "subtitle" in name]
