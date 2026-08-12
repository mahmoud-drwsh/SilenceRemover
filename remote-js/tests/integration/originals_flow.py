import hashlib
import json
import os
import time
import urllib.error
import urllib.request

BASE = "http://app:8080/projects/test-token/test-project"
SOURCE = "/fixtures/original.mp4"

def request(path, method="GET", payload=None, headers=None, absolute=False):
    body = payload if isinstance(payload, bytes) else (json.dumps(payload).encode() if payload is not None else None)
    all_headers = {"Content-Type": "application/json"} if body and not isinstance(payload, bytes) else {}
    all_headers.update(headers or {})
    target = path if absolute else BASE + path
    return urllib.request.urlopen(urllib.request.Request(target, data=body, headers=all_headers, method=method), timeout=20)

for _ in range(30):
    try:
        if request("http://app:8080/healthz", absolute=True).status == 200:
            break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("Media Manager did not become healthy")

# Startup backfill repairs pre-presigned-upload records which used the same
# pipeline ID as their original but did not store source_id.
legacy = json.load(request("/api/files?type=video&check_id=legacy-source-001"))
assert len(legacy) == 1 and legacy[0]["source_id"] == "legacy-source-001"
legacy_companions = json.load(request("/api/files?type=video&tags=no-overlay"))
assert any(item["id"] == "legacy-companion-001-no-overlay" for item in legacy_companions)
legacy_normal = next(item for item in json.load(request("/api/files?type=video")) if item["id"] == "legacy-companion-001")
assert legacy_normal["no_overlay_id"] == "legacy-companion-001-no-overlay"

with open(SOURCE, "rb") as handle:
    source = handle.read()
digest = hashlib.sha256(source).hexdigest()

def initiate(file_id, media_type, checksum, payload_bytes=source, mime_type="video/mp4", **extra):
    return json.load(request("/api/uploads/initiate", "POST", {
        "id": file_id, "type": media_type, "mime_type": mime_type,
        "file_size": len(payload_bytes), "checksum_sha256": checksum, **extra,
    }))

def complete_session(session, payload_bytes=source):
    part_size = session.get("part_size")
    if part_size:
        parts = []
        for part_number, url in enumerate(session["urls"], start=1):
            start = (part_number - 1) * part_size
            if url.startswith("/"):
                url = "http://app:8080" + url
            part = urllib.request.urlopen(urllib.request.Request(url, data=payload_bytes[start:start + part_size], method="PUT"), timeout=20)
            parts.append({"part_number": part_number, "etag": part.headers["ETag"]})
    else:
        part = urllib.request.urlopen(urllib.request.Request(session["upload_url"], data=payload_bytes, method="PUT"), timeout=20)
        parts = []
    return json.load(request(f"/api/uploads/{session['session_id']}/complete", "POST", {
        "parts": parts,
    }))

# The server verifies the stored bytes, not merely a client-provided hash.
bad_init = initiate("source-bad", "original", "0" * 64, original_filename="bad.mp4")
bad_part = urllib.request.urlopen(urllib.request.Request(bad_init["urls"][0], data=source, method="PUT"), timeout=20)
try:
    request(f"/api/uploads/{bad_init['session_id']}/complete", "POST", {
        "parts": [{"part_number": 1, "etag": bad_part.headers["ETag"]}],
    })
    raise AssertionError("checksum mismatch should fail completion")
except urllib.error.HTTPError as exc:
    assert exc.code == 400

init = initiate("source-001", "original", digest, original_filename="source.mp4")
assert init["ok"] and len(init["urls"]) == 1
completed = complete_session(init)
assert completed["ok"]

# Completing a verified original enqueues exactly one dormant source-processing
# record for explicitly enabled projects. Worker access uses a separate secret,
# while operational status and retries remain admin-only.
WORKER_BASE = "http://app:8080/internal/source-processing/test-project"
ADMIN_PROCESSING_BASE = "http://app:8080/admin/test-admin-token/api/projects/test-project/source-processing"

def processing_request(base, path, method="GET", payload=None, headers=None):
    return json.load(request(base + path, method, payload, headers, absolute=True))

try:
    processing_request(WORKER_BASE, "/claim", "POST", {})
    raise AssertionError("worker endpoint accepted a request without its dedicated token")
except urllib.error.HTTPError as exc:
    assert exc.code == 401

status = processing_request(ADMIN_PROCESSING_BASE, "/status")
assert status["states"] == {"pending": 1}
try:
    processing_request("http://app:8080/admin/test-token/api/projects/test-project/source-processing", "/status")
    raise AssertionError("media token was accepted as an admin credential")
except urllib.error.HTTPError as exc:
    assert exc.code == 401

claimed = processing_request(
    WORKER_BASE, "/claim", "POST", {}, {"X-Source-Processing-Token": "test-worker-token"},
)["job"]
assert claimed["source_id"] == "source-001" and claimed["original_checksum_sha256"] == digest

# A dead worker's short test lease expires and the next worker safely reclaims
# the same source rather than creating another job.
time.sleep(1.2)
for expired_action in ("heartbeat", "fail", "complete"):
    try:
        processing_request(
            WORKER_BASE, f"/{claimed['id']}/{expired_action}", "POST",
            {"lease_token": claimed["lease_token"], "error": "expired worker"},
            {"X-Source-Processing-Token": "test-worker-token"},
        )
        raise AssertionError(f"expired worker could call {expired_action}")
    except urllib.error.HTTPError as exc:
        assert exc.code == 409
reclaimed = processing_request(
    WORKER_BASE, "/claim", "POST", {}, {"X-Source-Processing-Token": "test-worker-token"},
)["job"]
assert reclaimed["id"] == claimed["id"] and reclaimed["lease_token"] != claimed["lease_token"]
for old_action in ("heartbeat", "fail", "complete"):
    try:
        processing_request(
            WORKER_BASE, f"/{claimed['id']}/{old_action}", "POST",
            {"lease_token": claimed["lease_token"], "error": "stale worker"},
            {"X-Source-Processing-Token": "test-worker-token"},
        )
        raise AssertionError(f"stale worker could call {old_action}")
    except urllib.error.HTTPError as exc:
        assert exc.code == 409
processing_request(
    WORKER_BASE, f"/{reclaimed['id']}/heartbeat", "POST",
    {"lease_token": reclaimed["lease_token"]}, {"X-Source-Processing-Token": "test-worker-token"},
)
processing_request(
    WORKER_BASE, f"/{reclaimed['id']}/fail", "POST",
    {"lease_token": reclaimed["lease_token"], "error": "intentional integration failure"},
    {"X-Source-Processing-Token": "test-worker-token"},
)
failed = processing_request(ADMIN_PROCESSING_BASE, "/status")
assert failed["states"] == {"failed": 1} and failed["failed"][0]["last_error"] == "intentional integration failure"
processing_request(ADMIN_PROCESSING_BASE, f"/{reclaimed['id']}/retry", "POST", {})
retry = processing_request(
    WORKER_BASE, "/claim", "POST", {}, {"X-Source-Processing-Token": "test-worker-token"},
)["job"]
processing_request(
    WORKER_BASE, f"/{retry['id']}/complete", "POST",
    {"lease_token": retry["lease_token"]}, {"X-Source-Processing-Token": "test-worker-token"},
)
assert processing_request(ADMIN_PROCESSING_BASE, "/status")["states"] == {"completed": 1}

# Repeating upload completion is idempotent and cannot enqueue a second job.
repeated_completion = json.load(request(f"/api/uploads/{init['session_id']}/complete", "POST", {"parts": []}))
assert repeated_completion["already_completed"]
assert processing_request(ADMIN_PROCESSING_BASE, "/status")["total"] == 1

# Projects not explicitly enabled retain the existing upload-only behavior and
# never create server-processing work.
DISABLED_BASE = "http://app:8080/projects/test-token/client-owned-project"
disabled_init = json.load(request(DISABLED_BASE + "/api/uploads/initiate", "POST", {
    "id": "client-owned-001", "type": "original", "mime_type": "video/mp4",
    "file_size": len(source), "checksum_sha256": digest, "original_filename": "client-owned.mp4",
}, absolute=True))
part = urllib.request.urlopen(urllib.request.Request(disabled_init["urls"][0], data=source, method="PUT"), timeout=20)
json.load(request(DISABLED_BASE + f"/api/uploads/{disabled_init['session_id']}/complete", "POST", {
    "parts": [{"part_number": 1, "etag": part.headers["ETag"]}],
}, absolute=True))
disabled_status = processing_request(
    "http://app:8080/admin/test-admin-token/api/projects/client-owned-project/source-processing", "/status",
)
assert disabled_status["enabled"] is False and disabled_status["total"] == 0
disabled_claim = processing_request(
    "http://app:8080/internal/source-processing/client-owned-project", "/claim", "POST", {},
    {"X-Source-Processing-Token": "test-worker-token"},
)
assert disabled_claim["job"] is None

originals = json.load(request("/api/files?type=original"))
assert any(item["id"] == "source-001" and item["checksum_sha256"] == digest for item in originals)
stream = request("/stream/source-001?type=original", headers={"Range": "bytes=0-99"})
assert stream.status == 206 and stream.read() == source[:100]
download = json.load(request("/api/originals/source-001/download"))
assert urllib.request.urlopen(download["url"], timeout=20).read() == source

video = complete_session(initiate("derived-001", "video", digest, title="Derived", tags=["pending"], source_id="source-001"))
assert video["ok"]
clean_video = complete_session(initiate("derived-001-no-overlay", "video", digest, title="Derived (No Overlay)", tags=["no-overlay"], source_id="source-001"))
assert clean_video["ok"]
needs_designer = json.load(request("/api/files?type=video&designer_missing=true"))
assert any(item["id"] == "derived-001" for item in needs_designer)
designer_video = complete_session(initiate("ignored-client-id", "video", digest, title="Designer revision", designer_of_id="derived-001"))
assert designer_video["ok"] and designer_video["id"] == "derived-001-designer"
derived = json.load(request("/api/originals/source-001/derived"))
assert {item["id"] for item in derived} == {"derived-001", "derived-001-no-overlay", "derived-001-designer"}
normal_videos = json.load(request("/api/files?type=video"))
normal = next(item for item in normal_videos if item["id"] == "derived-001")
assert normal["no_overlay_id"] == "derived-001-no-overlay"
assert normal["designer_video_id"] == "derived-001-designer"
assert all(item["id"] not in {"derived-001-no-overlay", "derived-001-designer"} for item in normal_videos)
needs_designer = json.load(request("/api/files?type=video&designer_missing=true"))
assert all(item["id"] != "derived-001" for item in needs_designer)
no_overlay_videos = json.load(request("/api/files?type=video&tags=no-overlay"))
assert any(item["id"] == "derived-001-no-overlay" for item in no_overlay_videos)
clean_stream = request("/stream/derived-001-no-overlay?type=video", headers={"Range": "bytes=0-99"})
assert clean_stream.status == 206 and clean_stream.read() == source[:100]

# A verified SRT creates durable, checksum-pinned jobs for every linked video
# variant. The worker uploads to a temporary key; completion atomically
# promotes it without changing titles, tags, or links.
srt = b"1\n00:00:00,000 --> 00:00:01,000\nArabic subtitle\n"
srt_digest = hashlib.sha256(srt).hexdigest()
srt_session = initiate(
    "source-001-subtitles", "subtitle", srt_digest, payload_bytes=srt,
    mime_type="application/x-subrip", title="Derived", source_id="source-001",
)
assert complete_session(srt_session, srt)["ok"]
enqueued = json.load(request("/api/remux/enqueue", "POST", {}))
assert enqueued["enqueued"] == 3
claimed = json.load(request("/api/remux/claim", "POST", {}))["job"]
assert claimed and claimed["input_checksum_sha256"] == digest
upload = json.load(request(f"/api/remux/{claimed['id']}/upload", "POST", {
    "lease_token": claimed["lease_token"], "size": len(source), "checksum_sha256": digest,
}))
urllib.request.urlopen(urllib.request.Request(
    upload["upload_url"], data=source, headers={"Content-Type": "video/mp4"}, method="PUT",
), timeout=20)
promoted = json.load(request(f"/api/remux/{claimed['id']}/complete", "POST", {
    "lease_token": claimed["lease_token"],
}))
assert promoted["ok"] and promoted["checksum_sha256"] == digest
status = json.load(request("/api/remux/status"))
assert status["states"]["completed"] == 1 and status["states"]["pending"] == 2

# The production pipeline's no-overlay videos are multipart uploads. Keep the
# MP4 header valid while crossing the 8 MiB multipart boundary.
multipart_clean = source + (b"\0" * (9 * 8 * 1024 * 1024))
multipart_digest = hashlib.sha256(multipart_clean).hexdigest()
multipart_session = initiate(
    "derived-multipart-no-overlay", "video", multipart_digest,
    payload_bytes=multipart_clean, title="Multipart (No Overlay)",
    tags=["no-overlay"], source_id="source-001",
)
assert multipart_session.get("part_size")
assert complete_session(multipart_session, multipart_clean)["ok"]
renamed_download = json.load(request("/api/originals/source-001/download"))
assert renamed_download["filename"] == "Derived.mp4"

# When a pipeline retry uploads a previously missing original, completing that
# upload self-heals a same-ID legacy derived row without a service restart.
legacy_video = complete_session(initiate("self-heal-001", "video", digest, title="Legacy retry", tags=["pending"]))
assert legacy_video["ok"]
self_heal_original = complete_session(initiate("self-heal-001", "original", digest, original_filename="self-heal.mp4"))
assert self_heal_original["ok"]
self_healed = json.load(request("/api/files?type=video&check_id=self-heal-001"))
assert len(self_healed) == 1 and self_healed[0]["source_id"] == "self-heal-001"

# file-type reports a real MKV as video/matroska; the server must normalize it
# to the pipeline's canonical video/x-matroska value before strict validation.
with open("/fixtures/original.mkv", "rb") as handle:
    mkv = handle.read()
mkv_digest = hashlib.sha256(mkv).hexdigest()
mkv_init = json.load(request("/api/uploads/initiate", "POST", {
    "id": "source-mkv-001", "type": "original", "original_filename": "source.mkv",
    "mime_type": "video/x-matroska", "file_size": len(mkv), "checksum_sha256": mkv_digest,
}))
mkv_part = urllib.request.urlopen(urllib.request.Request(mkv_init["urls"][0], data=mkv, method="PUT"), timeout=20)
mkv_complete = json.load(request(f"/api/uploads/{mkv_init['session_id']}/complete", "POST", {
    "parts": [{"part_number": 1, "etag": mkv_part.headers["ETag"]}],
}))
assert mkv_complete["ok"]
try:
    request("http://app:8080/public/test-token/test-project/api/originals/source-001/download", absolute=True)
except urllib.error.HTTPError as exc:
    assert exc.code == 404
print("isolated originals flow passed")
