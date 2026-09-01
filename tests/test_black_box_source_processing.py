from __future__ import annotations

from pathlib import Path

import pytest

from scripts.black_box_source_processing import (
    BOUNDED_ORIGINAL_BYTES,
    cleanup_artifacts,
    run_black_box,
    select_bounded_original,
)


class FakeClient:
    def __init__(self) -> None:
        self.files = {
            ("original", "source-small"): {"id": "source-small", "file_size": 12},
            ("audio", "black-box-test"): {
                "id": "black-box-test", "exists": True, "tags": ["todo"], "title": "generated"
            },
            ("subtitle", "black-box-test-subtitles"): {
                "id": "black-box-test-subtitles", "exists": True, "source_id": "black-box-test"
            },
            ("video", "black-box-test-no-overlay"): {
                "id": "black-box-test-no-overlay", "exists": True, "source_id": "black-box-test",
                "title": "approved", "duration": 25.1
            },
            ("video", "black-box-test"): {
                "id": "black-box-test", "exists": True, "source_id": "black-box-test",
                "title": "approved", "duration": 25.1
            },
        }
        self.approved = False
        self.deleted: list[tuple[str, str]] = []
        self.closed = False

    def get_original_files(self):
        return [self.files[("original", "source-small")]]

    def upload_original(self, source_id: str, path: Path):
        self.files[("original", source_id)] = {"id": source_id, "exists": True, "file_size": path.stat().st_size}
        return True

    def update_tags(self, file_id: str, tags: list[str], file_type: str = "audio"):
        if file_type == "audio":
            self.approved = tags == ["ready"]
        return True

    def approve_audio_title(self, source_id: str, title: str):
        self.approved = True
        self.files[("audio", source_id)] = {"id": source_id, "exists": True, "tags": ["ready"], "title": title}
        for file_type, file_id in (("video", source_id), ("video", f"{source_id}-no-overlay")):
            self.files[(file_type, file_id)]["title"] = title

    def close(self):
        self.closed = True

    def delete_file(self, file_id: str, file_type: str = "video"):
        self.deleted.append((file_id, file_type))
        return True


def test_bounded_selection_ignores_oversized_originals():
    rows = [{"id": "large", "file_size": BOUNDED_ORIGINAL_BYTES + 1}, {"id": "small", "file_size": 3}]
    assert select_bounded_original(rows) == rows[1]


def test_bounded_selection_requires_a_positive_size():
    assert select_bounded_original([{"id": "zero", "file_size": 0}, {"id": "bad", "file_size": "x"}]) is None


def test_run_requires_explicit_confirmation():
    with pytest.raises(ValueError, match="confirm-production"):
        run_black_box(FakeClient(), Path("/tmp/unused"), confirm_production=False)


def test_run_exercises_title_approval_and_both_variants_without_network(tmp_path: Path):
    client = FakeClient()
    result = run_black_box(
        client,
        tmp_path,
        confirm_production=True,
        source_id_factory=lambda: "black-box-test",
        download=lambda _client, _source, destination: destination.write_bytes(b"video"),
        make_clip_fn=lambda original, clip: clip.write_bytes(original.read_bytes()),
        wait=lambda _client, file_id, file_type, _timeout: client.files[(file_type, file_id)],
    )
    assert result["ok"] is True
    assert result["variants"] == ["no-overlay", "overlaid"]
    assert client.approved is True
    assert client.closed is True


def test_cleanup_attempts_every_artifact_after_failure():
    client = FakeClient()
    cleanup_artifacts(client, "black-box-test", wait=lambda *_args: (_ for _ in ()).throw(TimeoutError()))
    assert set(client.deleted) == {
        ("black-box-test", "original"), ("black-box-test", "audio"),
        ("black-box-test-subtitles", "subtitle"), ("black-box-test-no-overlay", "video"),
        ("black-box-test", "video"),
    }
    assert client.closed is False


def test_run_cleans_up_when_a_lifecycle_step_fails(tmp_path: Path):
    client = FakeClient()

    def failing_wait(_client, file_id, file_type, _timeout):
        if file_type == "subtitle":
            raise RuntimeError("worker failed")
        return client.files[(file_type, file_id)]

    with pytest.raises(RuntimeError, match="worker failed"):
        run_black_box(
            client, tmp_path, confirm_production=True,
            source_id_factory=lambda: "black-box-test",
            download=lambda _client, _source, destination: destination.write_bytes(b"video"),
            make_clip_fn=lambda original, clip: clip.write_bytes(original.read_bytes()),
            wait=failing_wait,
        )
    assert client.closed is True
    assert len(client.deleted) == 5
