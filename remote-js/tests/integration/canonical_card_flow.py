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
assert card["media_variant"] == "pipeline-final"
assert card["source_id"] == source_id
assert all(item["id"] not in {f"{final_id}-no-overlay", f"{final_id}-designer"} for item in normal)

no_overlay = json.load(request("/api/files?type=video&view=no-overlay"))
assert any(item["id"] == final_id for item in no_overlay)
assert all(item["id"] != f"{final_id}-no-overlay" for item in no_overlay)

# Read-side compatibility also collapses legacy deterministic designer IDs
# which predate designer_of_id, without changing their metadata.
legacy_source = f"legacy-designer-source-{run_id}"
legacy_final = f"legacy-designer-final-{run_id}"
assert upload(legacy_source, "original", original_filename="legacy-designer.mp4")["ok"]
assert upload(legacy_final, "video", title="Legacy final", source_id=legacy_source)["ok"]
assert upload(f"{legacy_final}-designer", "video", title="Legacy designer", source_id=legacy_source)["ok"]
legacy_cards = json.load(request("/api/files?type=video"))
legacy_card = next(item for item in legacy_cards if item["id"] == legacy_final)
assert legacy_card["designer_video_id"] == f"{legacy_final}-designer"
assert all(item["id"] != f"{legacy_final}-designer" for item in legacy_cards)
needs_designer = json.load(request("/api/files?type=video&view=needs-designer"))
assert all(item["id"] != legacy_final for item in needs_designer)

# The in-service rehearsal is report-only and sees both legacy and current rows.
rehearsal = json.load(request("/api/original-rooted-rehearsal"))
assert rehearsal["mode"] == "dry-run"
assert rehearsal["destructive_operations"] == 0
assert rehearsal["object_operations"] == 0
assert rehearsal["candidate_rows"] >= 5
assert rehearsal["safe_updates"] >= 5
print("isolated canonical card flow passed")
