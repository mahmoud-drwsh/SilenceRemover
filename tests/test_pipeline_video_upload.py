"""Tests for upload phase notifications and progress wiring."""

from __future__ import annotations

from pathlib import Path

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


def test_server_owned_pipeline_seeds_local_logo_without_replacing_server_logo(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    logo_path = tmp_path / "logo.png"
    logo_path.write_bytes(b"\x89PNG\r\n\x1a\nlocal-logo")
    calls: list[Path] = []

    class FakeClient:
        def upload_overlay_logo_if_missing(self, path: Path) -> bool:
            calls.append(path)
            return True

        def close(self):
            return None

    monkeypatch.setattr(pipeline, "DEFAULT_LOGO_PATH", logo_path)
    monkeypatch.setattr(pipeline, "MediaManagerClient", lambda _url: FakeClient())
    monkeypatch.setenv("MEDIA_MANAGER_URL", "https://example.test/projects/token/project/")

    pipeline.seed_server_overlay_logo_if_missing()

    assert calls == [logo_path]
    assert capsys.readouterr().out == "[Overlay Logo] Uploaded local logo to Media Manager\n"


def test_server_owned_pipeline_does_not_seed_a_missing_local_logo(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pipeline, "DEFAULT_LOGO_PATH", tmp_path / "missing.png")
    monkeypatch.setattr(pipeline, "MediaManagerClient", lambda _url: pytest.fail("client should not be created"))

    pipeline.seed_server_overlay_logo_if_missing()


def test_server_owned_pipeline_defers_failed_logo_seed_without_blocking_upload(
    monkeypatch, tmp_path: Path, capsys,
) -> None:
    logo_path = tmp_path / "logo.png"
    logo_path.write_bytes(b"\x89PNG\r\n\x1a\nlocal-logo")

    class FakeClient:
        def upload_overlay_logo_if_missing(self, _path: Path) -> bool:
            raise pipeline.MediaManagerError("connection reset")

        def close(self):
            return None

    monkeypatch.setattr(pipeline, "DEFAULT_LOGO_PATH", logo_path)
    monkeypatch.setattr(pipeline, "MediaManagerClient", lambda _url: FakeClient())
    monkeypatch.setenv("MEDIA_MANAGER_URL", "https://example.test/projects/token/project/")

    pipeline.seed_server_overlay_logo_if_missing()

    assert "[Overlay Logo] Deferred migration: connection reset" in capsys.readouterr().err


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


def test_existing_server_subtitle_skips_local_generation(tmp_path: Path) -> None:
    cache = pipeline.ServerDataCache(
        audio_files={},
        video_files={},
        original_files={},
        audio_trash_ids=frozenset(),
        video_trash_ids=frozenset(),
        ready_audio_ids=frozenset(),
        subtitle_files={"clip-subtitles": {"id": "clip-subtitles"}},
    )

    assert pipeline.existing_subtitle_skip_reason(tmp_path, "clip", cache) == (
        "subtitle already exists on server"
    )
    assert pipeline.existing_subtitle_skip_reason(tmp_path, "new-clip", cache) is None


def test_server_cache_resolves_no_overlay_from_pipeline_final_link() -> None:
    cache = pipeline.ServerDataCache(
        audio_files={},
        video_files={
            "clip": {
                "id": "clip",
                "no_overlay_id": "clip-no-overlay",
            },
        },
        original_files={},
        audio_trash_ids=frozenset(),
        video_trash_ids=frozenset(),
        ready_audio_ids=frozenset(),
    )

    assert cache.get_no_overlay_video("clip") == {"id": "clip-no-overlay"}
    assert cache.get_no_overlay_video("missing") is None


def test_local_subtitle_takes_precedence_over_server_skip(tmp_path: Path) -> None:
    subtitle_dir = tmp_path / "subtitles"
    subtitle_dir.mkdir()
    (subtitle_dir / "clip.srt").write_text("subtitle", encoding="utf-8")

    assert pipeline.existing_subtitle_skip_reason(tmp_path, "clip", None) == (
        "subtitle already exists"
    )


def test_run_video_upload_phase_notifies_on_success(
    monkeypatch,
    tmp_path: Path,
) -> None:
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

    upload_calls: list[tuple[str, str, Path]] = []
    notify_calls: list[tuple[int, int, str, str]] = []

    class FakeClient:
        def upload_video(
            self,
            file_id,
            title,
            output_path,
            tags,
            progress_callback,
            skip_if_exists_with_title,
            source_id=None,
        ):
            upload_calls.append((file_id, title, output_path))
            assert tags == ["pending"]
            assert callable(progress_callback)
            assert skip_if_exists_with_title is True
            assert source_id == "clip"
            progress_callback(512, 1024)
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

    result = pipeline.run_video_upload_phase(
        video_path=video_path,
        output_dir=output_dir,
        temp_dir=temp_dir,
        video_index=2,
        total_videos=5,
        server_cache=None,
    )

    assert result is True
    assert upload_calls == [("clip", "My Title", output_dir / "final-name.mp4")]
    assert notify_calls == [(2, 5, "clip.mkv", "My Title")]


def test_run_video_upload_phase_skips_notification_on_non_uploaded_result(
    monkeypatch,
    tmp_path: Path,
) -> None:
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

    notify_calls: list[tuple[int, int, str, str]] = []

    class FakeClient:
        def upload_video(
            self,
            file_id,
            title,
            output_path,
            tags,
            progress_callback,
            skip_if_exists_with_title,
            source_id=None,
        ):
            assert callable(progress_callback)
            assert skip_if_exists_with_title is True
            assert source_id == "clip"
            return {
                "success": True,
                "uploaded": False,
                "skipped": True,
                "overwritten": False,
            }

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

    result = pipeline.run_video_upload_phase(
        video_path=video_path,
        output_dir=output_dir,
        temp_dir=temp_dir,
        video_index=2,
        total_videos=5,
        server_cache=None,
    )

    assert result is True
    assert notify_calls == []


def test_no_overlay_variant_encodes_without_title_or_logo_and_uploads_with_same_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
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

    encode_calls: list[dict] = []
    upload_calls: list[tuple[str, str, Path, list[str], str]] = []

    monkeypatch.setattr(
        pipeline,
        "trim_single_video",
        lambda **kwargs: encode_calls.append(kwargs) or temp_dir / "no_overlay" / "final-name-no-overlay.mp4",
    )

    class FakeClient:
        def upload_video(self, file_id, title, output_path, tags, progress_callback, skip_if_exists_with_title, source_id=None):
            upload_calls.append((file_id, title, output_path, tags, source_id))
            return {"success": True, "uploaded": True, "skipped": False, "overwritten": False}

        def close(self):
            return None

    monkeypatch.setattr(pipeline, "MediaManagerClient", lambda _url: FakeClient())
    monkeypatch.setattr(
        pipeline,
        "_run_phase_step",
        lambda *, video_path, work_fn, video_index, total_videos, label: work_fn() or True,
    )

    assert pipeline.run_no_overlay_encode_phase(
        video_path=video_path,
        output_dir=output_dir,
        temp_dir=temp_dir,
        noise_threshold=-40.0,
        min_duration=0.2,
        pad_sec=0.1,
        target_length=178.0,
        trim_script_path=temp_dir / "trim.ffscript",
        encoder="libx265",
        video_index=1,
        total_videos=1,
    ) is True
    assert encode_calls == [{
        "input_file": video_path,
        "output_dir": temp_dir / "no_overlay",
        "noise_threshold": -40.0,
        "min_duration": 0.2,
        "pad_sec": 0.1,
        "target_length": 178.0,
        "output_basename": "final-name-no-overlay",
        "encoder": "libx265",
        "title_path": None,
        "title_font": None,
        "enable_title_overlay": False,
        "enable_logo_overlay": False,
        "title_y_fraction": None,
        "title_height_fraction": None,
        "temp_dir": temp_dir,
        "metadata_title": "My Title",
        "trim_script_path": temp_dir / "trim.ffscript",
    }]
    no_overlay_marker = temp_dir / "no_overlay_completed" / "clip.txt"
    assert no_overlay_marker.read_text(encoding="utf-8") == "final-name-no-overlay"
    assert pipeline.adopt_no_overlay_completion_or_get_skip_reason(temp_dir, "clip") == (
        "no-overlay encode already completed"
    )
    assert not (temp_dir / "no_overlay" / "final-name-no-overlay.mp4").exists()

    assert pipeline.run_no_overlay_video_upload_phase(
        video_path=video_path,
        output_dir=output_dir,
        temp_dir=temp_dir,
        video_index=1,
        total_videos=1,
    ) is True
    assert upload_calls == [
        (
            "clip-no-overlay",
            "My Title (No Overlay)",
            temp_dir / "no_overlay" / "final-name-no-overlay.mp4",
            ["no-overlay"],
            "clip",
        )
    ]


def test_no_overlay_encode_requires_final_completion_marker(tmp_path: Path) -> None:
    assert pipeline.adopt_no_overlay_completion_or_get_skip_reason(tmp_path, "clip") == (
        "final encode not completed"
    )


def test_no_overlay_encode_adopts_legacy_output_without_regenerating(
    tmp_path: Path,
) -> None:
    temp_dir = tmp_path / "temp"
    output_path = tmp_path / "generated-title-no-overlay.mp4"
    (temp_dir / "completed").mkdir(parents=True)
    (temp_dir / "completed" / "clip.txt").write_text(
        "generated-title", encoding="utf-8"
    )
    output_path.write_text("existing clean video", encoding="utf-8")

    assert pipeline.adopt_no_overlay_completion_or_get_skip_reason(
        temp_dir,
        "clip",
        expected_output_path=output_path,
    ) == "no-overlay encode already completed"
    output_path.unlink()

    assert pipeline.adopt_no_overlay_completion_or_get_skip_reason(
        temp_dir,
        "clip",
        expected_output_path=output_path,
    ) == "no-overlay encode already completed"
    assert (
        temp_dir / "no_overlay_completed" / "clip.txt"
    ).read_text(encoding="utf-8") == "generated-title-no-overlay"


def test_no_overlay_encode_adopts_uploaded_companion_after_local_move(
    tmp_path: Path,
) -> None:
    temp_dir = tmp_path / "temp"
    expected_output_path = tmp_path / "generated-title-no-overlay.mp4"
    (temp_dir / "completed").mkdir(parents=True)
    (temp_dir / "completed" / "clip.txt").write_text(
        "generated-title", encoding="utf-8"
    )

    assert pipeline.adopt_no_overlay_completion_or_get_skip_reason(
        temp_dir,
        "clip",
        expected_output_path=expected_output_path,
        already_uploaded=True,
    ) == "no-overlay encode already completed"
    assert not expected_output_path.exists()
    assert (
        temp_dir / "no_overlay_completed" / "clip.txt"
    ).read_text(encoding="utf-8") == "generated-title-no-overlay"


def test_no_overlay_reencodes_present_companion_with_wrong_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    temp_dir = tmp_path / "temp"
    expected_output_path = tmp_path / "generated-title-no-overlay.mp4"
    (temp_dir / "completed").mkdir(parents=True)
    (temp_dir / "completed" / "clip.txt").write_text("generated-title", encoding="utf-8")
    (temp_dir / "no_overlay_completed").mkdir()
    (temp_dir / "no_overlay_completed" / "clip.txt").write_text("generated-title-no-overlay", encoding="utf-8")
    expected_output_path.write_bytes(b"mkv bytes")
    monkeypatch.setattr(pipeline, "is_mp4_container", lambda _path: False)

    assert pipeline.adopt_no_overlay_completion_or_get_skip_reason(
        temp_dir, "clip", expected_output_path=expected_output_path,
    ) is None


def test_no_overlay_keeps_marker_when_companion_was_moved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    temp_dir = tmp_path / "temp"
    (temp_dir / "completed").mkdir(parents=True)
    (temp_dir / "completed" / "clip.txt").write_text("generated-title", encoding="utf-8")
    (temp_dir / "no_overlay_completed").mkdir()
    (temp_dir / "no_overlay_completed" / "clip.txt").write_text("generated-title-no-overlay", encoding="utf-8")
    monkeypatch.setattr(pipeline, "is_mp4_container", lambda _path: (_ for _ in ()).throw(AssertionError("moved file must not be probed")))

    assert pipeline.adopt_no_overlay_completion_or_get_skip_reason(
        temp_dir, "clip", expected_output_path=tmp_path / "missing.mp4",
    ) == "no-overlay encode already completed"
