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

with open(SOURCE, "rb") as handle:
    source = handle.read()
digest = hashlib.sha256(source).hexdigest()

def initiate(file_id, media_type, checksum, **extra):
    return json.load(request("/api/uploads/initiate", "POST", {
        "id": file_id, "type": media_type, "mime_type": "video/mp4",
        "file_size": len(source), "checksum_sha256": checksum, **extra,
    }))

def complete_session(session):
    part = urllib.request.urlopen(urllib.request.Request(session["urls"][0], data=source, method="PUT"), timeout=20)
    return json.load(request(f"/api/uploads/{session['session_id']}/complete", "POST", {
        "parts": [{"part_number": 1, "etag": part.headers["ETag"]}],
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
assert len(originals) == 1 and originals[0]["checksum_sha256"] == digest
stream = request("/stream/source-001?type=original", headers={"Range": "bytes=0-99"})
assert stream.status == 206 and stream.read() == source[:100]
download = json.load(request("/api/originals/source-001/download"))
assert urllib.request.urlopen(download["url"], timeout=20).read() == source

video = complete_session(initiate("derived-001", "video", digest, title="Derived", tags=["pending"], source_id="source-001"))
assert video["ok"]
derived = json.load(request("/api/originals/source-001/derived"))
assert len(derived) == 1 and derived[0]["id"] == "derived-001"

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
