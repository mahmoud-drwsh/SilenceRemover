"""End-to-end test for the server-owned source-processing worker.

This runs in the isolated Compose network after the existing Media Manager
flow.  It uploads one fixture through the public upload API, then runs the
real Python worker against the signed MinIO download URL. A deterministic fake
provider verifies that its review analysis matches the horizontal adapter.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from sr_source_processing import SourceProcessingWorker, WorkerConfig


APP = "http://app:8080"
PROJECT = "worker-project"
MEDIA_BASE = f"{APP}/projects/test-token/{PROJECT}"
WORKER_BASE = f"{APP}/internal/source-processing/{PROJECT}"
ADMIN_BASE = f"{APP}/admin/test-admin-token/api/projects/{PROJECT}/source-processing"
TOKEN = "test-worker-token"
SOURCE_ID = "worker-source-001"
FIXTURE = Path("/fixtures/fractional.mp4")
EXPECTED_REVIEW_ANALYSIS = {
    "transcript": "الحمد لله رب العالمين، اليوم نتحدث عن فضل طلب العلم.",
    "title": "اليوم نتحدث عن فضل طلب العلم",
}
EXPECTED_FRACTIONAL_DURATION = 25.124999
EXPECTED_INPUT_DURATION = 25.125


def request(url: str, method: str = "GET", payload: object | None = None, headers: dict[str, str] | None = None):
    if isinstance(payload, bytes):
        body = payload
    else:
        body = json.dumps(payload).encode() if payload is not None else None
    all_headers = {"Content-Type": "application/json"} if body and not isinstance(payload, bytes) else {}
    all_headers.update(headers or {})
    return urllib.request.urlopen(
        urllib.request.Request(url, data=body, headers=all_headers, method=method), timeout=30,
    )


def json_request(url: str, method: str = "GET", payload: object | None = None, headers: dict[str, str] | None = None) -> dict:
    return json.load(request(url, method, payload, headers))


def review_analysis_request(url: str, headers: dict[str, str] | None = None) -> dict:
    boundary = "review-analysis-integration-boundary"
    ogg = b"OggSintegration-review-audio"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"snippet\"; filename=\"review.ogg\"\r\n"
        "Content-Type: audio/ogg\r\n\r\n"
    ).encode() + ogg + f"\r\n--{boundary}--\r\n".encode()
    return json.load(request(
        url, "POST", body,
        {"Content-Type": f"multipart/form-data; boundary={boundary}", **(headers or {})},
    ))


for _ in range(30):
    try:
        if request(f"{APP}/healthz").status == 200:
            break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("Media Manager did not become healthy")

schema_check = subprocess.run(
    ["psql", "-h", "postgres", "-U", "media_manager", "-d", "media_manager", "-At", "-c",
     "SELECT c.data_type || ':' || f.duration::text FROM information_schema.columns c JOIN media_manager.files f ON f.id='legacy-source-001' AND f.type='original' WHERE c.table_schema='media_manager' AND c.table_name='files' AND c.column_name='duration'"],
    check=True, capture_output=True, text=True,
)
assert schema_check.stdout.strip() == "double precision:17", schema_check.stdout

# Both adapters must be indistinguishable when their shared provider sees the
# same transient OGG bytes. The worker route is authenticated separately.
horizontal_review = review_analysis_request(f"{MEDIA_BASE}/api/snippet-analysis")
server_review = review_analysis_request(
    f"{WORKER_BASE}/review-analysis", {"X-Source-Processing-Token": TOKEN},
)
assert horizontal_review == {"ok": True, **EXPECTED_REVIEW_ANALYSIS}
assert server_review == horizontal_review

source = FIXTURE.read_bytes()
digest = hashlib.sha256(source).hexdigest()

def initiate(file_id, media_type, checksum, payload_bytes=source, mime_type="video/mp4", **extra):
    return json_request(f"{MEDIA_BASE}/api/uploads/initiate", "POST", {
        "id": file_id, "type": media_type, "mime_type": mime_type,
        "file_size": len(payload_bytes), "checksum_sha256": checksum, **extra,
    })

def complete_session(session, payload_bytes=source):
    part_size = session.get("part_size")
    if part_size:
        parts = []
        for part_number, url in enumerate(session["urls"], start=1):
            start = (part_number - 1) * part_size
            if url.startswith("/"):
                url = APP + url
            part = request(url, "PUT", payload_bytes[start:start + part_size])
            parts.append({"part_number": part_number, "etag": part.headers["ETag"]})
    else:
        part = request(session["upload_url"], "PUT", payload_bytes)
        parts = []
    return json_request(f"{MEDIA_BASE}/api/uploads/{session['session_id']}/complete", "POST", {
        "parts": parts,
    })

init = json_request(f"{MEDIA_BASE}/api/uploads/initiate", "POST", {
    "id": SOURCE_ID,
    "type": "original",
    "mime_type": "video/mp4",
    "original_filename": "worker-source.mp4",
    "file_size": len(source),
    "checksum_sha256": digest,
})
upload = request(init["urls"][0], "PUT", source)
completed = json_request(f"{MEDIA_BASE}/api/uploads/{init['session_id']}/complete", "POST", {
    "parts": [{"part_number": 1, "etag": upload.headers["ETag"]}],
})
assert completed["ok"]

# Verify the control-plane payload before handing it to the worker. This also
# keeps failures actionable when the service and worker images are rebuilt
# independently.
probe = json_request(f"{WORKER_BASE}/claim", "POST", {}, {"X-Source-Processing-Token": TOKEN})
assert probe["job"] and probe["job"].get("original_download_url", "").startswith(("http://", "https://")), probe
probe_job = probe["job"]
json_request(
    f"{WORKER_BASE}/{probe_job['id']}/fail", "POST",
    {"lease_token": probe_job["lease_token"], "error": "payload preflight"},
    {"X-Source-Processing-Token": TOKEN},
)
json_request(f"{ADMIN_BASE}/{probe_job['id']}/retry", "POST", {})

def fake_subtitles(**kwargs):
    Path(kwargs["output_path"]).write_text("1\n00:00:00,000 --> 00:00:02,000\nنص اختبار\n", encoding="utf-8")

config = WorkerConfig(APP, PROJECT, TOKEN, Path("/tmp/source-processing-worker"), 0.2, openrouter_api_key="fake-provider-key")
def run_worker():
    with SourceProcessingWorker(
        config,
        subtitle_generator=fake_subtitles,
    ) as worker:
        assert worker.run_once()

run_worker()

status = json_request(f"{ADMIN_BASE}/status")
assert status["states"].get("waiting") == 1, status
waiting = status["waiting"]
assert len(waiting) == 1 and waiting[0]["source_id"] == SOURCE_ID
job_id = waiting[0]["id"]
checkpoint = waiting[0]["trim_plan"]
assert checkpoint["version"] == 1
assert checkpoint["source_id"] == SOURCE_ID
assert checkpoint["original_checksum_sha256"] == digest
assert checkpoint["plan"]["input_duration_sec"] == EXPECTED_INPUT_DURATION, checkpoint
assert checkpoint["plan"]["segments_to_keep"]
assert waiting[0]["review_transcript"] == EXPECTED_REVIEW_ANALYSIS["transcript"]
assert waiting[0]["generated_title"] == EXPECTED_REVIEW_ANALYSIS["title"]

# A reviewer edit and approval are user-owned metadata. The worker must pick
# the same waiting job back up without an admin retry or another model call.
json_request(f"{MEDIA_BASE}/api/files/{SOURCE_ID}?type=audio", "PUT", {"title": "عنوان راجعه المستخدم", "tags": ["ready"]})
run_worker()
status = json_request(f"{ADMIN_BASE}/status")
assert status["states"].get("completed") == 1, status
assert status["waiting"] == []
audio = json_request(f"{MEDIA_BASE}/api/files?type=audio&check_id={SOURCE_ID}")
subtitle = json_request(f"{MEDIA_BASE}/api/files?type=subtitle&check_id={SOURCE_ID}-subtitles")
assert audio[0]["title"] == "عنوان راجعه المستخدم" and audio[0]["tags"] == ["ready"]
assert audio[0]["source_id"] == SOURCE_ID and len(audio[0]["checksum_sha256"]) == 64
assert subtitle[0]["source_id"] == SOURCE_ID and len(subtitle[0]["checksum_sha256"]) == 64
served_srt = request(f"{MEDIA_BASE}/stream/{SOURCE_ID}-subtitles?type=subtitle").read()
served_audio = request(f"{MEDIA_BASE}/stream/{SOURCE_ID}?type=audio").read()
assert hashlib.sha256(served_audio).hexdigest() == audio[0]["checksum_sha256"]
assert hashlib.sha256(served_srt).hexdigest() == subtitle[0]["checksum_sha256"]
assert b"00:00:00,000 --> 00:00:02,000" in served_srt
videos = json_request(f"{MEDIA_BASE}/api/files?type=video&include_pending=true")
no_overlay_videos = json_request(f"{MEDIA_BASE}/api/files?type=video&check_id={SOURCE_ID}-no-overlay")
video_by_id = {video["id"]: video for video in videos + no_overlay_videos}
assert set(video_by_id) >= {SOURCE_ID, f"{SOURCE_ID}-no-overlay"}
assert video_by_id[SOURCE_ID]["title"] == "عنوان راجعه المستخدم"
assert video_by_id[SOURCE_ID]["media_variant"] == "pipeline-final"
assert video_by_id[SOURCE_ID]["publication_status"] == "published"
assert video_by_id[f"{SOURCE_ID}-no-overlay"]["tags"] == ["no-overlay"]
for video_id in (SOURCE_ID, f"{SOURCE_ID}-no-overlay"):
    assert video_by_id[video_id]["source_id"] == SOURCE_ID
    # The legacy-seed service intentionally changes files.duration back to
    # integer before the app starts. These public final-file responses prove
    # startup migration restored double precision and preserved the known
    # fractional render duration through artifact completion and serialization.
    assert video_by_id[video_id]["duration"] == EXPECTED_FRACTIONAL_DURATION, video_by_id[video_id]
    served = request(f"{MEDIA_BASE}/stream/{video_id}?type=video").read()
    assert hashlib.sha256(served).hexdigest() == video_by_id[video_id]["checksum_sha256"]
    local_video = Path(f"/tmp/{video_id}.mp4")
    local_video.write_bytes(served)
    subtitle_probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "s:0", "-show_entries", "stream=codec_name:stream_disposition=default", "-of", "json", str(local_video)],
        check=True, capture_output=True, text=True,
    )
    subtitle_stream = json.loads(subtitle_probe.stdout)["streams"]
    assert subtitle_stream[0]["codec_name"] == "mov_text"
print("isolated source-processing worker flow passed")
