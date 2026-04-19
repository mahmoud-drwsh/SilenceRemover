"""Tests for Phase 9 video upload notifications."""

from __future__ import annotations

from pathlib import Path

from src.app import pipeline


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
        def upload_video(self, file_id, title, output_path, tags, progress_callback):
            upload_calls.append((file_id, title, output_path))
            assert tags == ["pending"]
            assert progress_callback is None
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
        def upload_video(self, file_id, title, output_path, tags, progress_callback):
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
