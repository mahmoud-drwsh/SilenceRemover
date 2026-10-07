import hashlib
import io
import json
import os
import time
import urllib.error
import urllib.request
import wave

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

# Startup is read-only for legacy relationships. The separate rehearsal tool
# is the only path that may populate missing links after its dry-run report.
legacy = json.load(request("/api/files?type=video&check_id=legacy-source-001"))
assert len(legacy) == 1 and legacy[0]["source_id"] is None

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

# Every verified original uses server processing by default.
DISABLED_BASE = "http://app:8080/projects/test-token/client-owned-project"
disabled_init = json.load(request(DISABLED_BASE + "/api/uploads/initiate", "POST", {
    "id": "client-owned-001", "type": "original", "mime_type": "video/mp4",
    "file_size": len(source), "checksum_sha256": digest, "original_filename": "client-owned.mp4",
}, absolute=True))
part = urllib.request.urlopen(urllib.request.Request(disabled_init["urls"][0], data=source, method="PUT"), timeout=20)
json.load(request(DISABLED_BASE + f"/api/uploads/{disabled_init['session_id']}/complete", "POST", {
    "parts": [{"part_number": 1, "etag": part.headers["ETag"]}],
}, absolute=True))
default_status = processing_request(
    "http://app:8080/admin/test-admin-token/api/projects/client-owned-project/source-processing", "/status",
)
assert default_status["enabled"] is True and default_status["states"] == {"pending": 1}
default_claim = processing_request(
    "http://app:8080/internal/source-processing/client-owned-project", "/claim", "POST", {},
    {"X-Source-Processing-Token": "test-worker-token"},
)
assert default_claim["job"]["source_id"] == "client-owned-001"

originals = json.load(request("/api/files?type=original"))
assert any(item["id"] == "source-001" and item["checksum_sha256"] == digest for item in originals)
stream = request("/stream/source-001?type=original", headers={"Range": "bytes=0-99"})
assert stream.status == 206 and stream.read() == source[:100]
download = json.load(request("/api/originals/source-001/download"))
assert urllib.request.urlopen(download["url"], timeout=20).read() == source

def status_of(path, method="GET", payload=None, headers=None, absolute=False):
    """Return the HTTP status code of a request that can fail."""
    try:
        return request(path, method, payload, headers, absolute).status
    except urllib.error.HTTPError as exc:
        return exc.code

# Since #44 the no-overlay video is the only pipeline video and the canonical
# card. Its designer revisions and its original are actions on that card.
NO_OVERLAY = {"media_variant": "no-overlay", "visibility": "active", "publication_status": "published"}
card_id = "derived-001-no-overlay"
clean_video = complete_session(initiate(card_id, "video", digest, title="Derived", tags=[], source_id="source-001", **NO_OVERLAY))
assert clean_video["ok"] and clean_video["id"] == card_id
needs_designer = json.load(request("/api/files?type=video&designer_missing=true"))
assert any(item["id"] == card_id for item in needs_designer)
designer_video = complete_session(initiate("ignored-client-id", "video", digest, title="Designer revision", designer_of_id=card_id))
assert designer_video["ok"] and designer_video["id"].startswith(f"{card_id}-designer-")
designer_video_id = designer_video["id"]
designer_video_next = complete_session(initiate("ignored-client-id", "video", digest, title="Designer revision 2", designer_of_id=card_id))
assert designer_video_next["ok"] and designer_video_next["id"].startswith(f"{card_id}-designer-")
designer_video_next_id = designer_video_next["id"]
assert designer_video_next_id != designer_video_id
derived = json.load(request("/api/originals/source-001/derived"))
assert {item["id"] for item in derived} == {card_id, designer_video_id, designer_video_next_id}
normal_videos = json.load(request("/api/files?type=video"))
normal = next(item for item in normal_videos if item["id"] == card_id)
assert normal["media_variant"] == "no-overlay" and normal["title"] == "Derived"
assert normal["designer_video_id"] == designer_video_next_id
assert normal["active_designer_revision_id"] == designer_video_next_id
assert "no_overlay_id" not in normal and "subtitle_id" not in normal
assert all(item["id"] not in {designer_video_id, designer_video_next_id} for item in normal_videos)
needs_designer = json.load(request("/api/files?type=video&designer_missing=true"))
assert all(item["id"] != card_id for item in needs_designer)
# A removed view name opens All.
removed_view = json.load(request("/api/files?type=video&view=no-overlay"))
assert {item["id"] for item in removed_view} == {item["id"] for item in normal_videos}
clean_stream = request(f"/stream/{card_id}?type=video", headers={"Range": "bytes=0-99"})
assert clean_stream.status == 206 and clean_stream.read() == source[:100]

# Review audio uploads still work.
wav_buffer = io.BytesIO()
with wave.open(wav_buffer, "wb") as wav_writer:
    wav_writer.setnchannels(1)
    wav_writer.setsampwidth(2)
    wav_writer.setframerate(8000)
    wav_writer.writeframes(b"\0\0" * 8000)
wav = wav_buffer.getvalue()
wav_digest = hashlib.sha256(wav).hexdigest()
audio = complete_session(initiate(
    "source-001", "audio", wav_digest, payload_bytes=wav, mime_type="audio/wav",
    title="Derived", source_id="source-001",
), wav)
assert audio["ok"] and audio["type"] == "audio"
audio_rows = json.load(request("/api/files?type=audio&check_id=source-001"))
assert audio_rows[0]["review_status"] == "todo" and audio_rows[0]["source_id"] == "source-001"

# New uploads cannot use the removed subtitle type or pipeline-final variant.
srt = b"1\n00:00:00,000 --> 00:00:01,000\nArabic subtitle\n"
assert status_of("/api/uploads/initiate", "POST", {
    "id": "source-001-subtitles", "type": "subtitle", "mime_type": "application/x-subrip",
    "file_size": len(srt), "checksum_sha256": hashlib.sha256(srt).hexdigest(),
    "title": "Derived", "source_id": "source-001",
}) == 400
assert status_of("/api/uploads/initiate", "POST", {
    "id": "source-001", "type": "video", "mime_type": "video/mp4",
    "file_size": len(source), "checksum_sha256": digest, "title": "Derived",
    "tags": [], "source_id": "source-001", "media_variant": "pipeline-final",
    "visibility": "active", "publication_status": "published",
}) == 400
assert status_of("/api/files?type=subtitle") == 400
assert status_of("/stream/source-001-subtitles?type=subtitle") == 400

# The remux queue and the overlay logo routes are removed.
for method, path in (
    ("POST", "/api/remux/enqueue"), ("POST", "/api/remux/claim"),
    ("POST", "/api/remux/job-001/upload"), ("POST", "/api/remux/job-001/complete"),
    ("POST", "/api/remux/job-001/fail"), ("POST", "/api/remux/checksum/source-001"),
    ("GET", "/api/remux/status"),
    ("POST", "/api/overlay-logo-if-missing/initiate"),
    ("POST", "/api/overlay-logo-if-missing/complete"),
):
    assert status_of(path, method, {}) == 404, (method, path)
assert status_of("/api/overlay-logo-if-missing", "PUT", b"\x89PNG", {"Content-Type": "image/png"}) == 404
assert status_of(
    "http://app:8080/admin/test-admin-token/api/projects/test-project/overlay-logo", "POST",
    b"\x89PNG", {"Content-Type": "image/png"}, absolute=True,
) == 404
assert status_of(
    f"{WORKER_BASE}/{retry['id']}/overlay-logo",
    headers={"X-Source-Processing-Token": "test-worker-token"}, absolute=True,
) == 404
admin_projects = json.load(request("http://app:8080/admin/test-admin-token/api/projects", absolute=True))
assert all("overlay_logo_configured" not in project for project in admin_projects["projects"])

# New derived uploads must name their original; legacy rows are repaired only
# by the explicit, rehearsed backfill and are never recreated by this API.
try:
    initiate("self-heal-001-no-overlay", "video", digest, title="Legacy retry", tags=[], **NO_OVERLAY)
    raise AssertionError("derived upload without source_id should fail")
except urllib.error.HTTPError as exc:
    assert exc.code == 400
self_heal_original = complete_session(initiate("self-heal-001", "original", digest, original_filename="self-heal.mp4"))
assert self_heal_original["ok"]
legacy_video = complete_session(initiate("self-heal-001-no-overlay", "video", digest, title="Linked retry", tags=[], source_id="self-heal-001", **NO_OVERLAY))
assert legacy_video["ok"]
self_healed = json.load(request("/api/files?type=video&check_id=self-heal-001-no-overlay"))
assert len(self_healed) == 1 and self_healed[0]["source_id"] == "self-heal-001"

# Drive a real original-processing job to waiting before deleting its original.
# This avoids testing a merely dormant job: waiting work must not be able to
# resume once the original and its artifacts have been removed.
waiting_claim = processing_request(
    WORKER_BASE, "/claim", "POST", {}, {"X-Source-Processing-Token": "test-worker-token"},
)["job"]
assert waiting_claim and waiting_claim["source_id"] == "self-heal-001"
processing_request(
    WORKER_BASE, f"/{waiting_claim['id']}/waiting", "POST",
    {"lease_token": waiting_claim["lease_token"], "reason": "waiting for title review"},
    {"X-Source-Processing-Token": "test-worker-token"},
)
waiting_status = processing_request(ADMIN_PROCESSING_BASE, "/status")
assert waiting_status["states"].get("waiting") == 1

# A failed job is terminal and must stay failed if its original is later
# deleted, just as the completed source-001 job must stay completed.
failed_original = complete_session(initiate(
    "failed-delete-001", "original", digest, original_filename="failed-delete.mp4",
))
assert failed_original["ok"]
failed_claim = processing_request(
    WORKER_BASE, "/claim", "POST", {}, {"X-Source-Processing-Token": "test-worker-token"},
)["job"]
assert failed_claim and failed_claim["source_id"] == "failed-delete-001"
processing_request(
    WORKER_BASE, f"/{failed_claim['id']}/fail", "POST",
    {"lease_token": failed_claim["lease_token"], "error": "terminal deletion fixture"},
    {"X-Source-Processing-Token": "test-worker-token"},
)

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

# Deleting trashed originals stale only non-terminal work in the same metadata
# transaction. The waiting and pending jobs cannot resume, while completed and
# failed jobs retain their terminal states.
for original_id in ("self-heal-001", "source-001", "failed-delete-001", "source-mkv-001"):
    request(f"/api/files/{original_id}?type=original", "PUT", {"tags": ["trash"]})
    deleted = json.load(request(f"/api/files/{original_id}?type=original", "DELETE"))
    assert deleted["ok"] and deleted["deleted"]
after_delete = processing_request(ADMIN_PROCESSING_BASE, "/status")
assert after_delete["states"] == {"completed": 1, "failed": 1, "stale": 2}
assert after_delete["waiting"] == []
assert after_delete["failed"][0]["source_id"] == "failed-delete-001"
assert after_delete["failed"][0]["last_error"] == "terminal deletion fixture"
post_delete_claim = processing_request(
    WORKER_BASE, "/claim", "POST", {}, {"X-Source-Processing-Token": "test-worker-token"},
)
assert post_delete_claim["job"] is None
print("isolated originals flow passed")
