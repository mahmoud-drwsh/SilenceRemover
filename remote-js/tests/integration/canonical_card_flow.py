"""Verify that derived variants remain actions on one canonical video card."""

import hashlib
import json
import urllib.request
import uuid


BASE = "http://app:8080/projects/test-token/test-project"


def request(path, method="GET", payload=None, absolute=False):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    target = path if absolute else BASE + path
    return urllib.request.urlopen(
        urllib.request.Request(target, data=body, headers=headers, method=method),
        timeout=20,
    )


with open("/fixtures/original.mp4", "rb") as handle:
    video_bytes = handle.read()
digest = hashlib.sha256(video_bytes).hexdigest()


def upload(file_id, media_type, **extra):
    session = json.load(request("/api/uploads/initiate", "POST", {
        "id": file_id,
        "type": media_type,
        "mime_type": "video/mp4",
        "file_size": len(video_bytes),
        "checksum_sha256": digest,
        **extra,
    }))
    upload_url = session["urls"][0]
    if upload_url.startswith("/"):
        upload_url = "http://app:8080" + upload_url
    part = urllib.request.urlopen(
        urllib.request.Request(upload_url, data=video_bytes, method="PUT"), timeout=20,
    )
    return json.load(request(f"/api/uploads/{session['session_id']}/complete", "POST", {
        "parts": [{"part_number": 1, "etag": part.headers["ETag"]}],
    }))


run_id = uuid.uuid4().hex
source_id = f"canonical-card-source-{run_id}"
final_id = f"canonical-card-final-{run_id}"
assert upload(source_id, "original", original_filename="canonical.mp4")["ok"]
assert upload(final_id, "video", title="Canonical", tags=["pending"], source_id=source_id)["ok"]
assert upload(
    f"{final_id}-no-overlay",
    "video",
    title="Canonical no overlay",
    tags=["no-overlay"],
    source_id=source_id,
)["ok"]
designer = upload("ignored-client-id", "video", title="Designer revision", designer_of_id=final_id)
assert designer["id"] == f"{final_id}-designer"

normal = json.load(request("/api/files?type=video"))
card = next(item for item in normal if item["id"] == final_id)
assert card["no_overlay_id"] == f"{final_id}-no-overlay"
assert card["designer_video_id"] == f"{final_id}-designer"
assert all(item["id"] not in {f"{final_id}-no-overlay", f"{final_id}-designer"} for item in normal)

no_overlay = json.load(request("/api/files?type=video&tags=no-overlay"))
assert any(item["id"] == f"{final_id}-no-overlay" for item in no_overlay)
print("isolated canonical card flow passed")
