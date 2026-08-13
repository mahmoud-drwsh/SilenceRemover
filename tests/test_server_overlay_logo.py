from __future__ import annotations

from pathlib import Path

import httpx

from sr_source_processing import SourceProcessingWorker, WorkerConfig


PNG = b"\x89PNG\r\n\x1a\nminimal-png-payload"


def test_worker_downloads_project_logo_with_lease_fenced_worker_auth(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/job-001/overlay-logo")
        assert request.headers["X-Source-Processing-Token"] == "worker-secret"
        assert request.headers["X-Source-Processing-Lease-Token"] == "lease-001"
        return httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})

    worker = SourceProcessingWorker(
        WorkerConfig("https://service.example.test", "project-a", "worker-secret", tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    logo = worker._download_project_logo("job-001", "lease-001", tmp_path)
    assert logo == tmp_path / "project-overlay-logo.png"
    assert logo.read_bytes() == PNG


def test_worker_allows_a_project_without_a_configured_logo(tmp_path: Path) -> None:
    worker = SourceProcessingWorker(
        WorkerConfig("https://service.example.test", "project-a", "worker-secret", tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(404))),
    )
    assert worker._download_project_logo("job-001", "lease-001", tmp_path) is None
