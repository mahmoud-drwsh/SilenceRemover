"""Focused contract tests for the server worker that makes only the no-overlay video."""

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
    def audio(_input: Path, output: Path, _segments: list[tuple[float, float]]) -> None:
        output.write_bytes(b"review-audio")

    def review_analysis_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/review-analysis"):
            return httpx.Response(200, json={"ok": True, "transcript": "نص المراجعة", "title": "عنوان"})
        return handler.handle_request(request)

    worker = SourceProcessingWorker(
        WorkerConfig("https://service.example.test", "project-a", "worker-secret", tmp_path, heartbeat),
        client=httpx.Client(transport=httpx.MockTransport(review_analysis_handler)), trim_planner=planner,
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
        WorkerConfig("https://service.example.test", "project-a", "worker-secret", tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)), trim_planner=_plan,
        review_audio_builder=audio,
    )
    worker._has_audio = lambda _path: True

    assert worker.run_once() is True
    assert review_analysis_requests == 1
    assert all("srt_text" not in body for body in checkpoint_bodies)
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
        "review_audio_uploaded": True,
    })
    review_analysis_requests = 0

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
        WorkerConfig("https://service.example.test", "project-a", "worker-secret", tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)), trim_planner=lambda **_: (_ for _ in ()).throw(AssertionError("trim plan must be reused")),
        review_audio_builder=lambda *_: (_ for _ in ()).throw(AssertionError("review OGG must not be rebuilt")),
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


def test_idle_worker_prerenders_no_overlay_video_and_reuses_it_after_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sr_source_processing.api as worker_api

    payload = b"two-second-media-bytes"
    checkpoints: dict[str, object] = {}
    checkpoint_bodies: list[dict[str, object]] = []
    uploads: list[tuple[str, str]] = []
    paths: list[str] = []
    claims = [_job(payload)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "objects.example.test":
            return httpx.Response(200, content=payload)
        paths.append(request.url.path)
        body = json.loads(request.content or b"{}")
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"ok": True, "job": claims.pop(0) if claims else None})
        if request.url.path.endswith("/checkpoints"):
            checkpoint_bodies.append(body)
            checkpoints.update({key: value for key, value in body.items() if key != "lease_token"})
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/artifacts/initiate"):
            uploads.append((body["kind"], body["title"]))
            return httpx.Response(200, json={"ok": True, "already_uploaded": True})
        if request.url.path.endswith(("/artifacts/complete", "/waiting", "/complete")):
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    encodes: list[tuple[str, str | None]] = []
    titled: list[tuple[str, str]] = []

    def fake_trim(*, output_dir: Path, output_basename: str, metadata_title: str | None = None, **_: object) -> Path:
        encodes.append((output_basename, metadata_title))
        output = output_dir / f"{output_basename}.mp4"
        output.write_bytes(output_basename.encode())
        return output

    monkeypatch.setattr(worker_api, "trim_single_video", fake_trim)
    monkeypatch.setattr(worker_api, "write_trim_script_from_plan", lambda **kwargs: kwargs["temp_dir"] / "trim.txt")
    monkeypatch.setattr(
        worker_api.SourceProcessingWorker, "_set_metadata_title",
        staticmethod(lambda video, title: titled.append((video.name, title))),
    )
    worker = _worker(tmp_path, httpx.MockTransport(handler))
    worker._duration = lambda _path: 2.0
    job_dir = tmp_path / "project-a" / "job-001"

    # Before approval: the review audio first, then the idle-time encode.
    assert worker.run_once() is True
    assert encodes == []
    assert uploads == [("review_audio", "عنوان")]
    assert (job_dir / "awaiting-title-review.json").is_file()
    assert worker.run_once() is False
    assert worker.prerender_once() is True
    assert encodes == [("no-overlay.prerender", None)]
    assert worker.prerender_once() is False

    # After approval: no new encode. The prerender gets the approved title by remux.
    uploads.clear()
    approved = {**_job(payload), **checkpoints, "approved_title": "العنوان المعتمد",
                "review_audio_uploaded": True}
    claims.append(approved)
    assert worker.run_once() is True
    assert encodes == [("no-overlay.prerender", None)]
    assert titled == [("no-overlay.mp4", "العنوان المعتمد")]
    assert uploads == [("no_overlay_video", "العنوان المعتمد")]
    assert paths[-1].endswith("/job-001/complete")
    assert all("srt_text" not in body for body in checkpoint_bodies)
    assert not any("logo" in path for path in paths)
    assert not (job_dir / "awaiting-title-review.json").exists()
    assert worker.prerender_once() is False


def test_failed_prerender_falls_back_to_normal_encode_after_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sr_source_processing.api as worker_api

    job_dir = tmp_path / "project-a" / "job-001"
    job_dir.mkdir(parents=True)
    (job_dir / "awaiting-title-review.json").write_text(
        json.dumps({"original_filename": "recording.mp4", "original_checksum_sha256": "abc"}), encoding="utf-8",
    )
    (job_dir / "trim-plan.json").write_text(json.dumps({"plan": {"segments_to_keep": [[0.0, 2.0]]}}), encoding="utf-8")

    def broken_trim(**_: object) -> Path:
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr(worker_api, "trim_single_video", broken_trim)
    monkeypatch.setattr(worker_api, "write_trim_script_from_plan", lambda **kwargs: kwargs["temp_dir"] / "trim.txt")
    worker = _worker(tmp_path, httpx.MockTransport(lambda _request: httpx.Response(500)))

    assert worker.prerender_once() is True
    assert (job_dir / "no-overlay.prerender.failed").is_file()
    # A failed encode is not retried in a loop; the post-approval path encodes normally.
    assert worker.prerender_once() is False
    assert worker._take_prerender(job_dir, worker._prerender_key("abc", [(0.0, 2.0)]), job_dir / "no-overlay.mp4") is False


def test_idle_worker_seeds_prerender_from_server_for_jobs_without_local_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sr_source_processing.api as worker_api

    payload = b"two-second-media-bytes"
    job = _job(payload)
    checksum = str(job["original_checksum_sha256"])
    trim_plan = {
        "version": 1, "source_id": "source-001", "original_checksum_sha256": checksum,
        "plan": {"segments_to_keep": [[0.0, 2.0]]},
    }
    excludes: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "objects.example.test":
            assert "X-Source-Processing-Token" not in request.headers
            return httpx.Response(200, content=payload)
        assert request.url.path.endswith("/prerender-candidate")
        exclude = json.loads(request.content)["exclude"]
        excludes.append(exclude)
        if "job-001" in exclude:
            return httpx.Response(200, json={"ok": True, "job": None})
        return httpx.Response(200, json={"ok": True, "job": {
            "id": "job-001", "source_id": "source-001", "original_checksum_sha256": checksum,
            "trim_plan": trim_plan, "original_download_url": job["original_download_url"],
            "original_filename": "recording.mp4",
        }})

    encodes: list[str] = []

    def fake_trim(*, output_dir: Path, output_basename: str, **_: object) -> Path:
        encodes.append(output_basename)
        output = output_dir / f"{output_basename}.mp4"
        output.write_bytes(b"video")
        return output

    monkeypatch.setattr(worker_api, "trim_single_video", fake_trim)
    monkeypatch.setattr(worker_api, "write_trim_script_from_plan", lambda **kwargs: kwargs["temp_dir"] / "trim.txt")
    worker = _worker(tmp_path, httpx.MockTransport(handler))
    job_dir = tmp_path / "project-a" / "job-001"

    assert worker.prerender_once() is True
    assert (job_dir / "recording.mp4").read_bytes() == payload
    assert encodes == ["no-overlay.prerender"]
    # The finished job is excluded from the next seed request.
    assert worker.prerender_once() is False
    assert excludes == [[], ["job-001"]]


def test_prerender_seed_tolerates_a_server_without_the_endpoint(tmp_path: Path) -> None:
    worker = _worker(tmp_path, httpx.MockTransport(lambda _request: httpx.Response(404, json={"ok": False})))
    assert worker.prerender_once() is False


def test_approved_job_without_prerender_encodes_and_uploads_one_titled_no_overlay_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sr_source_processing.api as worker_api

    payload = b"two-second-media-bytes"
    job = {
        **_job(payload),
        "trim_plan": {
            "version": 1, "source_id": "source-001",
            "original_checksum_sha256": hashlib.sha256(payload).hexdigest(),
            "plan": {"segments_to_keep": [[0.0, 2.0]]},
        },
        "approved_title": "العنوان المعتمد",
        # An old server can still send these fields. The worker ignores them.
        "srt_text": "", "subtitle_uploaded": False, "overlaid_uploaded": False,
    }
    claims = [job]
    uploads: list[tuple[str, str]] = []
    paths: list[str] = []
    encodes: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "objects.example.test":
            return httpx.Response(200, content=payload)
        paths.append(request.url.path)
        body = json.loads(request.content or b"{}")
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"ok": True, "job": claims.pop(0) if claims else None})
        if request.url.path.endswith("/artifacts/initiate"):
            uploads.append((body["kind"], body["title"]))
            return httpx.Response(200, json={"ok": True, "already_uploaded": True})
        if request.url.path.endswith(("/artifacts/complete", "/complete")):
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    def fake_trim(*, output_dir: Path, output_basename: str, metadata_title: str | None = None, **_: object) -> Path:
        encodes.append((output_basename, metadata_title))
        output = output_dir / f"{output_basename}.mp4"
        output.write_bytes(b"video")
        return output

    monkeypatch.setattr(worker_api, "trim_single_video", fake_trim)
    monkeypatch.setattr(worker_api, "write_trim_script_from_plan", lambda **kwargs: kwargs["temp_dir"] / "trim.txt")
    worker = _worker(tmp_path, httpx.MockTransport(handler))
    worker._duration = lambda _path: 2.0
    # A failed prerender must not block the normal encode after approval.
    job_dir = tmp_path / "project-a" / "job-001"
    job_dir.mkdir(parents=True)
    (job_dir / "no-overlay.prerender.failed").write_text("ffmpeg failed", encoding="utf-8")

    assert worker.run_once() is True
    assert encodes == [("no-overlay", "العنوان المعتمد")]
    assert uploads == [("no_overlay_video", "العنوان المعتمد")]
    assert paths[-1].endswith("/job-001/complete")
    assert not any("logo" in path for path in paths)


def test_worker_config_needs_no_openrouter_key_or_overlay_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("OPENROUTER_API_KEY", "SOURCE_PROCESSING_ENCODER", "SOURCE_PROCESSING_HEARTBEAT_INTERVAL_SEC"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SOURCE_PROCESSING_SERVICE_URL", "https://service.example.test/")
    monkeypatch.setenv("SOURCE_PROCESSING_PROJECT", "project-a")
    monkeypatch.setenv("SOURCE_PROCESSING_WORKER_TOKEN", "worker-secret")
    monkeypatch.setenv("SOURCE_PROCESSING_WORK_DIR", str(tmp_path))
    # Old overlay settings can stay in an old env file. The worker ignores them.
    monkeypatch.setenv("SOURCE_PROCESSING_ENABLE_TITLE_OVERLAY", "true")
    monkeypatch.setenv("SOURCE_PROCESSING_ENABLE_LOGO_OVERLAY", "true")

    config = WorkerConfig.from_env()

    assert config.service_url == "https://service.example.test"
    assert config.encoder == "X265"
    assert not any(field in vars(config) for field in (
        "openrouter_api_key", "enable_title_overlay", "enable_logo_overlay", "title_font",
    ))
