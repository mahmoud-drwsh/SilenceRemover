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

def initiate(file_id, media_type, checksum, payload_bytes=source, **extra):
    return json.load(request("/api/uploads/initiate", "POST", {
        "id": file_id, "type": media_type, "mime_type": "video/mp4",
        "file_size": len(payload_bytes), "checksum_sha256": checksum, **extra,
    }))

def complete_session(session, payload_bytes=source):
    part_size = session.get("part_size")
    if part_size:
        parts = []
        for part_number, url in enumerate(session["urls"], start=1):
            start = (part_number - 1) * part_size
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
designer_video = complete_session(initiate("ignored-client-id", "video", digest, title="Designer revision", designer_of_id="derived-001"))
assert designer_video["ok"] and designer_video["id"] == "derived-001-designer"
derived = json.load(request("/api/originals/source-001/derived"))
assert {item["id"] for item in derived} == {"derived-001", "derived-001-no-overlay", "derived-001-designer"}
normal_videos = json.load(request("/api/files?type=video"))
normal = next(item for item in normal_videos if item["id"] == "derived-001")
assert normal["no_overlay_id"] == "derived-001-no-overlay"
assert normal["designer_video_id"] == "derived-001-designer"
assert all(item["id"] not in {"derived-001-no-overlay", "derived-001-designer"} for item in normal_videos)
no_overlay_videos = json.load(request("/api/files?type=video&tags=no-overlay"))
assert any(item["id"] == "derived-001-no-overlay" for item in no_overlay_videos)
clean_stream = request("/stream/derived-001-no-overlay?type=video", headers={"Range": "bytes=0-99"})
assert clean_stream.status == 206 and clean_stream.read() == source[:100]

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
