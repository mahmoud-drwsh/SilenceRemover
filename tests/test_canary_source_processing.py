from __future__ import annotations

from pathlib import Path

import httpx

from scripts.canary_source_processing import analyze_review_audio


class FakeMediaManager:
    base_url = "https://media.example.test"
    project = "project-a"

    def __init__(self) -> None:
        self.request: httpx.Request | None = None
        self._client = httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.request = request
        return httpx.Response(200, json={"ok": True, "transcript": "نص", "title": "عنوان"})


def test_canary_uses_worker_authenticated_review_analysis_adapter(tmp_path: Path) -> None:
    audio = tmp_path / "review.ogg"
    audio.write_bytes(b"OggScanary")
    client = FakeMediaManager()

    assert analyze_review_audio(client, "worker-token", audio) == ("نص", "عنوان")
    assert client.request is not None
    assert client.request.url.path == "/internal/source-processing/project-a/review-analysis"
    assert client.request.headers["X-Source-Processing-Token"] == "worker-token"
    assert b"OggScanary" in client.request.content
