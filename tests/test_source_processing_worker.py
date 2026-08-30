"""Focused contract tests for the trim-plan-only server worker slice."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from sr_source_processing import SourceProcessingWorker, WorkerConfig, WorkerError
from sr_trim_plan import TrimPlan, build_trim_plan


def _job(payload: bytes) -> dict[str, object]:
    return {
        "id": "job-001",
        "source_id": "source-001",
        "lease_token": "lease-001",
        "original_checksum_sha256": hashlib.sha256(payload).hexdigest(),
        "original_download_url": "https://objects.example.test/original.mp4?signature=unrelated",
        "original_filename": "recording.mp4",
    }


def _plan(input_file: Path, **_: object) -> TrimPlan:
    return TrimPlan(
        mode="non_target", segments_to_keep=[(0.0, 2.0)], input_duration_sec=2.0,
        resulting_length_sec=2.0, resolved_noise_threshold=-50.0,
        resolved_min_duration=1.0, resolved_pad_sec=0.5, target_length=None,
    )


def _worker(tmp_path: Path, handler: httpx.MockTransport, planner=_plan, heartbeat=30.0) -> SourceProcessingWorker:
    def subtitles(**kwargs: object) -> None:
        Path(kwargs["output_path"]).write_text("1\n00:00:00,000 --> 00:00:02,000\nنص\n", encoding="utf-8")
    def audio(_input: Path, output: Path, _segments: list[tuple[float, float]]) -> None:
        output.write_bytes(b"review-audio")

    def review_analysis_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/review-analysis"):
            return httpx.Response(200, json={"ok": True, "transcript": "نص المراجعة", "title": "عنوان"})
        return handler.handle_request(request)

    worker = SourceProcessingWorker(
        WorkerConfig("https://service.example.test", "project-a", "worker-secret", tmp_path, heartbeat, openrouter_api_key="test-key"),
        client=httpx.Client(transport=httpx.MockTransport(review_analysis_handler)), trim_planner=planner,
        subtitle_generator=subtitles,
        review_audio_builder=audio,
    )
    worker._has_audio = lambda _path: True
    return worker


def test_worker_checkpoints_and_waits_without_sending_worker_secret_to_object_store(tmp_path: Path) -> None:
    payload = b"two-second-media-bytes"
    job = _job(payload)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "objects.example.test":
            assert "X-Source-Processing-Token" not in request.headers
            return httpx.Response(200, content=payload)
        assert request.headers["X-Source-Processing-Token"] == "worker-secret"
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"ok": True, "job": job})
        if request.url.path.endswith("/checkpoints"):
            body = json.loads(request.content)
            if "trim_plan" in body:
                checkpoint = body["trim_plan"]
                assert checkpoint["source_id"] == "source-001"
                assert checkpoint["plan"]["segments_to_keep"] == [[0.0, 2.0]]
            return httpx.Response(200, json={"ok": True})
        if "/artifacts/" in request.url.path:
            if request.url.path.endswith("/initiate"):
                return httpx.Response(200, json={"ok": True, "already_uploaded": True, "id": "artifact"})
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/waiting"):
            assert json.loads(request.content)["reason"] == "waiting for title review"
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    worker = _worker(tmp_path, httpx.MockTransport(handler))
    assert worker.run_once() is True
    assert (tmp_path / "project-a" / "job-001" / "trim-plan.json").is_file()
    assert seen[-1].url.path.endswith("/waiting")


def test_worker_uses_internal_review_analysis_once_and_checkpoints_its_result(tmp_path: Path) -> None:
    """The server worker delegates review analysis to Media Manager, once per claim."""
    payload = b"two-second-media-bytes"
    job = _job(payload)
    review_analysis_requests = 0
    checkpoint_bodies: list[dict[str, object]] = []

    def subtitles(**kwargs: object) -> None:
        Path(kwargs["output_path"]).write_text("1\n00:00:00,000 --> 00:00:02,000\nنص\n", encoding="utf-8")

    def audio(_input: Path, output: Path, _segments: list[tuple[float, float]]) -> None:
        output.write_bytes(b"OggSreview-audio")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal review_analysis_requests
        if request.url.host == "objects.example.test":
            return httpx.Response(200, content=payload)
        assert request.headers["X-Source-Processing-Token"] == "worker-secret"
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"ok": True, "job": job})
        if request.url.path.endswith("/review-analysis"):
            review_analysis_requests += 1
            assert request.headers["Content-Type"].startswith("multipart/form-data;")
            assert b'OggSreview-audio' in request.content
            return httpx.Response(200, json={"ok": True, "transcript": "نص المراجعة", "title": "عنوان"})
        if request.url.path.endswith("/checkpoints"):
            checkpoint_bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})
        if "/artifacts/" in request.url.path:
            return httpx.Response(200, json={"ok": True, "already_uploaded": True, "id": "artifact"})
        if request.url.path.endswith("/waiting"):
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    worker = SourceProcessingWorker(
        WorkerConfig("https://service.example.test", "project-a", "worker-secret", tmp_path, openrouter_api_key="subtitle-key"),
        client=httpx.Client(transport=httpx.MockTransport(handler)), trim_planner=_plan,
        subtitle_generator=subtitles, review_audio_builder=audio,
    )
    worker._has_audio = lambda _path: True

    assert worker.run_once() is True
    assert review_analysis_requests == 1
    assert any(
        body.get("review_transcript") == "نص المراجعة" and body.get("generated_title") == "عنوان"
        for body in checkpoint_bodies
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required to generate the isolated media fixture")
def test_worker_computes_real_two_second_trim_plan_without_openrouter(tmp_path: Path) -> None:
    original = tmp_path / "fixture.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=15",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "2",
        "-c:v", "mpeg4", "-c:a", "aac", str(original),
    ], check=True, capture_output=True)
    payload = original.read_bytes()
    job = _job(payload)
    checkpoint: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "objects.example.test":
            return httpx.Response(200, content=payload)
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"ok": True, "job": job})
        if request.url.path.endswith("/checkpoints"):
            body = json.loads(request.content)
            if "trim_plan" in body:
                checkpoint.update(body["trim_plan"])
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/waiting"):
            return httpx.Response(200, json={"ok": True})
        if "/artifacts/" in request.url.path:
            return httpx.Response(200, json={"ok": True, "already_uploaded": True, "id": "artifact"})
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/checkpoints"):
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/artifacts/initiate"):
            return httpx.Response(200, json={"ok": True, "already_uploaded": True, "id": "artifact"})
        if request.url.path.endswith("/artifacts/complete"):
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    worker = _worker(tmp_path, httpx.MockTransport(handler), planner=build_trim_plan, heartbeat=0.01)
    assert worker.run_once() is True
    plan = checkpoint["plan"]
    assert isinstance(plan, dict)
    assert plan["input_duration_sec"] == pytest.approx(2.0, abs=0.1)
    assert plan["segments_to_keep"]


def test_worker_stops_heartbeat_thread_before_returning(tmp_path: Path) -> None:
    payload = b"heartbeat-media"
    job = _job(payload)
    heartbeats = 0

    def slow_plan(input_file: Path, **_: object) -> TrimPlan:
        time.sleep(0.04)
        return _plan(input_file)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal heartbeats
        if request.url.host == "objects.example.test":
            return httpx.Response(200, content=payload)
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"ok": True, "job": job})
        if request.url.path.endswith("/heartbeat"):
            heartbeats += 1
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/artifacts/initiate"):
            return httpx.Response(200, json={"ok": True, "already_uploaded": True, "id": "artifact"})
        return httpx.Response(200, json={"ok": True})

    worker = _worker(tmp_path, httpx.MockTransport(handler), planner=slow_plan, heartbeat=0.01)
    assert worker.run_once() is True
    assert heartbeats >= 1
    after_return = heartbeats
    time.sleep(0.03)
    assert heartbeats == after_return


def test_waiting_retry_reuses_valid_checkpoint_without_replanning(tmp_path: Path) -> None:
    payload = b"unchanged-original"
    job = _job(payload)
    job["trim_plan"] = {
        "version": 1,
        "source_id": "source-001",
        "original_checksum_sha256": hashlib.sha256(payload).hexdigest(),
        "plan": {"segments_to_keep": [[0.0, 2.0]], "input_duration_sec": 2.0},
    }
    calls = 0
    paths: list[str] = []

    def planner(*_: object, **__: object) -> TrimPlan:
        nonlocal calls
        calls += 1
        return _plan(Path())

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.host == "objects.example.test":
            return httpx.Response(200, content=payload)
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"ok": True, "job": job})
        if request.url.path.endswith("/waiting"):
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/checkpoints"):
            return httpx.Response(200, json={"ok": True})
        if "/artifacts/" in request.url.path:
            return httpx.Response(200, json={"ok": True, "already_uploaded": True, "id": "artifact"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    worker = _worker(tmp_path, httpx.MockTransport(handler), planner=planner)
    assert worker.run_once() is True
    assert calls == 0
    saved = json.loads((tmp_path / "project-a" / "job-001" / "trim-plan.json").read_text())
    assert saved == job["trim_plan"]


def test_waiting_retry_reuses_review_analysis_checkpoints_without_a_second_request(tmp_path: Path) -> None:
    payload = b"unchanged-original"
    job = _job(payload)
    job.update({
        "trim_plan": {
            "version": 1, "source_id": "source-001",
            "original_checksum_sha256": hashlib.sha256(payload).hexdigest(),
            "plan": {"segments_to_keep": [[0.0, 2.0]], "input_duration_sec": 2.0},
        },
        "review_transcript": "محفوظ", "generated_title": "عنوان محفوظ",
        "srt_text": "1\n00:00:00,000 --> 00:00:02,000\nنص\n",
        "review_audio_uploaded": True, "subtitle_uploaded": True,
    })
    review_analysis_requests = 0

    def subtitles(**kwargs: object) -> None:
        Path(kwargs["output_path"]).write_text("1\n00:00:00,000 --> 00:00:02,000\nنص\n", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal review_analysis_requests
        if request.url.host == "objects.example.test":
            return httpx.Response(200, content=payload)
        if request.url.path.endswith("/review-analysis"):
            review_analysis_requests += 1
            return httpx.Response(500)
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"ok": True, "job": job})
        if request.url.path.endswith("/waiting") or request.url.path.endswith("/checkpoints") or "/artifacts/" in request.url.path:
            return httpx.Response(200, json={"ok": True, "already_uploaded": True, "id": "artifact"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    worker = SourceProcessingWorker(
        WorkerConfig("https://service.example.test", "project-a", "worker-secret", tmp_path, openrouter_api_key="subtitle-key"),
        client=httpx.Client(transport=httpx.MockTransport(handler)), trim_planner=lambda **_: (_ for _ in ()).throw(AssertionError("trim plan must be reused")),
        subtitle_generator=subtitles, review_audio_builder=lambda *_: (_ for _ in ()).throw(AssertionError("review OGG must not be rebuilt")),
    )
    worker._has_audio = lambda _path: True

    assert worker.run_once() is True
    assert review_analysis_requests == 0


def test_waiting_retry_reuses_empty_plan_for_silent_source(tmp_path: Path) -> None:
    payload = b"silent-original"
    job = _job(payload)
    job["trim_plan"] = {
        "version": 1,
        "source_id": "source-001",
        "original_checksum_sha256": hashlib.sha256(payload).hexdigest(),
        "plan": {"segments_to_keep": [], "input_duration_sec": 2.0},
    }

    def planner(*_: object, **__: object) -> TrimPlan:
        raise AssertionError("a valid empty trim plan must be reused")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "objects.example.test":
            return httpx.Response(200, content=payload)
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"ok": True, "job": job})
        if request.url.path.endswith("/waiting"):
            return httpx.Response(200, json={"ok": True})
        if "/artifacts/" in request.url.path:
            return httpx.Response(200, json={"ok": True, "already_uploaded": True, "id": "artifact"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    worker = _worker(tmp_path, httpx.MockTransport(handler), planner=planner)
    assert worker.run_once() is True


def test_changed_original_fails_before_checkpoint_or_waiting(tmp_path: Path) -> None:
    job = _job(b"expected-original")
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.host == "objects.example.test":
            return httpx.Response(200, content=b"mutated-original")
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"ok": True, "job": job})
        if request.url.path.endswith("/fail"):
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    worker = _worker(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(WorkerError, match="checksum"):
        worker.run_once()
    assert any(path.endswith("/fail") for path in paths)
    assert all(not path.endswith("/checkpoints") and not path.endswith("/waiting") for path in paths)


def test_audio_less_source_waits_without_model_calls(tmp_path: Path) -> None:
    payload = b"video-only"
    job = _job(payload)
    reasons: list[str] = []
    worker = _worker(tmp_path, httpx.MockTransport(lambda request: (
        httpx.Response(200, content=payload) if request.url.host == "objects.example.test" else
        httpx.Response(200, json={"ok": True, "job": job}) if request.url.path.endswith("/claim") else
        (reasons.append(json.loads(request.content)["reason"]) or httpx.Response(200, json={"ok": True})) if request.url.path.endswith("/waiting") else
        httpx.Response(200, json={"ok": True})
    )))
    worker._has_audio = lambda _path: False
    assert worker.run_once()
    assert reasons == ["trim-plan-ready; source has no audio"]
