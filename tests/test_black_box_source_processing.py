from __future__ import annotations

from pathlib import Path
import json

import httpx
import pytest

from scripts.black_box_source_processing import (
    BOUNDED_ORIGINAL_BYTES,
    cleanup_artifacts,
    approve_title,
    redact_text,
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

    def verify_absent(self, _file_id: str, _file_type: str):
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
        health=lambda _client: None,
        serve=lambda _client, _file_id, _file_type: None,
    )
    assert result["ok"] is True
    assert result["variants"] == ["no-overlay", "overlaid"]
    assert client.approved is True
    assert client.closed is True


def test_approval_uses_raw_http_production_api_branch():
    class RawClient:
        base_url = "https://media.example.test"

        def __init__(self):
            self._client = httpx.Client(transport=httpx.MockTransport(self.handle))
            self.request = None

        def _url(self, endpoint):
            return "https://media.example.test/projects/token/project" + endpoint

        def handle(self, request):
            self.request = request
            return httpx.Response(200, json={"ok": True})

    client = RawClient()
    approve_title(client, "source-1", "عنوان الاختبار")
    assert client.request.url.path.endswith("/api/files/source-1")
    assert client.request.url.params["type"] == "audio"
    assert json.loads(client.request.read()) == {"title": "عنوان الاختبار", "tags": ["ready"]}


def test_cleanup_attempts_every_artifact_after_failure():
    client = FakeClient()
    cleanup_artifacts(
        client,
        "black-box-test",
        wait=lambda *_args: (_ for _ in ()).throw(TimeoutError()),
        attempts=1,
    )
    assert set(client.deleted) == {
        ("black-box-test", "original"), ("black-box-test", "audio"),
        ("black-box-test-subtitles", "subtitle"), ("black-box-test-no-overlay", "video"),
        ("black-box-test", "video"),
    }
    assert client.closed is False


class LateArtifactClient:
    """A cleanup fake where a worker publishes one artifact after pass one."""

    def __init__(self) -> None:
        self.remaining = {
            ("video", "source"),
            ("video", "source-no-overlay"),
            ("subtitle", "source-subtitles"),
            ("audio", "source"),
            ("original", "source"),
        }
        self.delete_calls: list[tuple[str, str]] = []
        self.late_published = False

    def delete_file(self, file_id: str, file_type: str = "video") -> bool:
        item = (file_type, file_id)
        self.delete_calls.append((file_id, file_type))
        self.remaining.discard(item)
        return True

    def verify_absent(self, file_id: str, file_type: str) -> bool:
        return (file_type, file_id) not in self.remaining

    def publish_late_subtitle(self) -> None:
        if not self.late_published:
            self.late_published = True
            self.remaining.add(("subtitle", "source-subtitles"))


def test_cleanup_retries_until_late_worker_artifact_is_absent():
    client = LateArtifactClient()
    failures = cleanup_artifacts(
        client,
        "source",
        attempts=3,
        retry_delay_seconds=0,
        sleep=lambda _seconds: client.publish_late_subtitle(),
    )
    assert failures == []
    assert client.remaining == set()
    assert client.delete_calls.count(("source-subtitles", "subtitle")) == 2


class FailedCleanupClient(FakeClient):
    def __init__(self, failed_type: str = "video") -> None:
        super().__init__()
        self.failed_type = failed_type

    def delete_file(self, file_id: str, file_type: str = "video"):
        self.deleted.append((file_id, file_type))
        if file_type == self.failed_type:
            return False
        return True


def test_cleanup_reports_delete_failure_precisely():
    failures = cleanup_artifacts(
        FailedCleanupClient(),
        "black-box-test",
        attempts=2,
        retry_delay_seconds=0,
        sleep=lambda _seconds: None,
    )
    assert any("delete returned an unsuccessful result" in failure for failure in failures)
    assert any("video:black-box-test" in failure for failure in failures)


def test_cleanup_reports_raw_trash_failure_without_attempting_delete():
    class RawFailureClient:
        def __init__(self):
            self.deleted = False

        def update_tags(self, _file_id, _tags, _file_type):
            return False

    client = RawFailureClient()
    failures = cleanup_artifacts(
        client,
        "source",
        attempts=1,
        sleep=lambda _seconds: None,
    )
    assert failures
    assert all("trash returned an unsuccessful result" in failure for failure in failures)
    assert client.deleted is False


def test_cleanup_redacts_credentials_and_signed_urls():
    message = redact_text("request failed Authorization: Bearer secret")
    url_message = redact_text("signed upload https://host.example/upload?X-Amz-Signature=abc")
    assert "secret" not in message
    assert "X-Amz-Signature" not in url_message
    assert "<redacted-url>" in url_message


def test_lifecycle_error_remains_primary_when_cleanup_and_close_fail(tmp_path: Path):
    class FailingClient(FailedCleanupClient):
        def close(self):
            raise RuntimeError("close leaked token=close-secret")

    client = FailingClient()
    with pytest.raises(RuntimeError, match="primary lifecycle failure") as raised:
        run_black_box(
            client,
            tmp_path,
            confirm_production=True,
            source_id_factory=lambda: "black-box-test",
            health=lambda _client: (_ for _ in ()).throw(RuntimeError("primary lifecycle failure")),
            cleanup_attempts=1,
            cleanup_sleep=lambda _seconds: None,
        )
    assert "Cleanup diagnostics:" in "\n".join(raised.value.__notes__)
    assert "Client close failed:" in "\n".join(raised.value.__notes__)
    assert "close-secret" not in "\n".join(raised.value.__notes__)


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
            health=lambda _client: None,
            serve=lambda _client, _file_id, _file_type: None,
            cleanup_attempts=1,
            cleanup_sleep=lambda _seconds: None,
        )
    assert client.closed is True
    assert len(client.deleted) == 5
