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

# The server must verify the claimed digest after S3 completes the multipart
# upload; a client-provided hash alone is not trusted.
bad_init = json.load(request("/api/originals/source-bad/upload", "POST", {
    "original_filename": "bad.mp4", "mime_type": "video/mp4",
    "file_size": len(source), "checksum_sha256": "0" * 64,
}))
bad_part = urllib.request.urlopen(urllib.request.Request(bad_init["urls"][0], data=source, method="PUT"), timeout=20)
try:
    request("/api/originals/source-bad/complete", "POST", {
        "upload_id": bad_init["upload_id"],
        "parts": [{"part_number": 1, "etag": bad_part.headers["ETag"]}],
    })
    raise AssertionError("checksum mismatch should fail completion")
except urllib.error.HTTPError as exc:
    assert exc.code == 400

init = json.load(request("/api/originals/source-001/upload", "POST", {
    "original_filename": "source.mp4", "mime_type": "video/mp4",
    "file_size": len(source), "checksum_sha256": digest,
}))
assert init["ok"] and not init.get("already_uploaded") and len(init["urls"]) == 1
part = urllib.request.urlopen(urllib.request.Request(init["urls"][0], data=source, method="PUT"), timeout=20)
etag = part.headers.get("ETag")
assert etag
complete = json.load(request("/api/originals/source-001/complete", "POST", {
    "upload_id": init["upload_id"], "parts": [{"part_number": 1, "etag": etag}],
}))
assert complete["ok"]

originals = json.load(request("/api/files?type=original"))
assert len(originals) == 1 and originals[0]["checksum_sha256"] == digest
stream = request("/stream/source-001?type=original", headers={"Range": "bytes=0-99"})
assert stream.status == 206 and stream.read() == source[:100]
download = json.load(request("/api/originals/source-001/download"))
assert urllib.request.urlopen(download["url"], timeout=20).read() == source

video = request("/api/files/derived-001/content?title=Derived&tags=%5B%22pending%22%5D&source_id=source-001", "PUT", source, {"Content-Type": "video/mp4", "Content-Length": str(len(source))})
assert video.status == 200
derived = json.load(request("/api/originals/source-001/derived"))
assert len(derived) == 1 and derived[0]["id"] == "derived-001"
try:
    request("http://app:8080/public/test-token/test-project/api/originals/source-001/download", absolute=True)
except urllib.error.HTTPError as exc:
    assert exc.code == 404
print("isolated originals flow passed")
