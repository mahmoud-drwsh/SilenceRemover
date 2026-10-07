"""Verify that the no-overlay video is the canonical video card (#45).

The flow seeds legacy rows with SQL, because the API no longer makes them:
an overlaid video (variant pipeline-final, ID `<source_id>`), designer
revisions that point at the overlaid ID, a legacy `-designer` row, and an
active designer revision pointer on the overlaid row. It then checks that the
card list, the views, the designer upload and the download names use the
no-overlay video, with the legacy links still visible.
"""

import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


APP = "http://app:8080"
BASE = f"{APP}/projects/test-token/test-project"
PROJECT = "test-project"


def request(path, method="GET", payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    return urllib.request.urlopen(
        urllib.request.Request(BASE + path, data=body, headers=headers, method=method),
        timeout=20,
    )


def psql(statement):
    result = subprocess.run(
        ["psql", "-h", "postgres", "-U", "media_manager", "-d", "media_manager",
         "-v", "ON_ERROR_STOP=1", "-At", "-c", statement],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def literal(value):
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


for _ in range(60):
    try:
        if urllib.request.urlopen(f"{APP}/healthz", timeout=5).status == 200:
            break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("Media Manager did not become healthy")


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
        upload_url = APP + upload_url
    part = urllib.request.urlopen(
        urllib.request.Request(upload_url, data=video_bytes, method="PUT"), timeout=20,
    )
    return json.load(request(f"/api/uploads/{session['session_id']}/complete", "POST", {
        "parts": [{"part_number": 1, "etag": part.headers["ETag"]}],
    }))


def upload_no_overlay(source_id, title):
    assert upload(source_id, "original", original_filename=f"{source_id}.mp4")["ok"]
    result = upload(
        f"{source_id}-no-overlay", "video", title=title, tags=[], source_id=source_id,
        media_variant="no-overlay", visibility="active", publication_status="published",
    )
    assert result["ok"] and result["id"] == f"{source_id}-no-overlay"
    return result["id"]


def seed_video(file_id, title, source_id, *, variant=None, designer_of_id=None,
               active_pointer=None, created_at="now()"):
    """Insert a legacy video row with no S3 object."""
    psql(
        "INSERT INTO media_manager.files (id, project, type, title, tags, duration, file_size, "
        "mime_type, created_at, source_id, designer_of_id, active_designer_revision_id, "
        "media_variant, visibility, publication_status) VALUES ("
        f"{literal(file_id)}, {literal(PROJECT)}, 'video', {literal(title)}, '[]'::jsonb, 2, "
        f"{len(video_bytes)}, 'video/mp4', {created_at}, {literal(source_id)}, "
        f"{literal(designer_of_id)}, {literal(active_pointer)}, {literal(variant)}, "
        "'active', 'published')"
    )


def video_list(query=""):
    return json.load(request(f"/api/files?type=video{query}"))


def card_for(cards, card_id):
    return next(item for item in cards if item["id"] == card_id)


def download_name(file_id):
    response = request(f"/stream/{urllib.parse.quote(file_id)}?type=video")
    response.read()
    disposition = response.headers["Content-Disposition"]
    return urllib.parse.unquote(disposition.split("filename*=UTF-8''", 1)[1])


def expect_http_error(status, call):
    try:
        call()
    except urllib.error.HTTPError as error:
        assert error.code == status, (error.code, error.read())
        return
    raise AssertionError(f"expected HTTP {status}")


run_id = uuid.uuid4().hex

# Case A: an overlaid video holds the approved title, two explicit designer
# revisions and the active pointer. Its no-overlay companion is from the PC
# pipeline, so its own title has the old "(No Overlay)" suffix.
source_a = f"canonical-a-{run_id}"
card_a = upload_no_overlay(source_a, "Approved A (No Overlay)")
legacy_newer = f"{source_a}-designer-legacy-newer"
legacy_active = f"{source_a}-designer-legacy-active"
seed_video(source_a, "Approved A", source_a, variant="pipeline-final", active_pointer=legacy_active)
seed_video(legacy_newer, "Approved A", source_a, variant="designer", designer_of_id=source_a,
           created_at="now() + interval '1 hour'")
seed_video(legacy_active, "Approved A", source_a, variant="designer", designer_of_id=source_a)

# Case B: a legacy `-designer` row without designer_of_id or variant.
source_b = f"canonical-b-{run_id}"
card_b = upload_no_overlay(source_b, "Approved B")
seed_video(source_b, "Approved B", source_b, variant="pipeline-final")
seed_video(f"{source_b}-designer", "Approved B", source_b)

# Case C: no designer revision yet.
source_c = f"canonical-c-{run_id}"
card_c = upload_no_overlay(source_c, "Approved C")
seed_video(source_c, "Approved C", source_c, variant="pipeline-final")

cards = video_list()
card_ids = {item["id"] for item in cards}
for removed in (source_a, source_b, source_c, legacy_newer, legacy_active, f"{source_b}-designer"):
    assert removed not in card_ids, removed

listed_a = card_for(cards, card_a)
assert listed_a["media_variant"] == "no-overlay"
assert listed_a["source_id"] == source_a
assert listed_a["title"] == "Approved A"
# The legacy pointer on the overlaid row wins over the newer legacy revision.
assert listed_a["active_designer_revision_id"] == legacy_active
assert listed_a["designer_video_id"] == legacy_active

listed_b = card_for(cards, card_b)
assert listed_b["designer_video_id"] == f"{source_b}-designer"
assert listed_b["active_designer_revision_id"] is None

listed_c = card_for(cards, card_c)
assert listed_c["designer_video_id"] is None

needs_designer = {item["id"] for item in video_list("&view=needs-designer")}
assert card_c in needs_designer
assert card_a not in needs_designer and card_b not in needs_designer
designer_missing = {item["id"] for item in video_list("&designer_missing=true")}
assert designer_missing == needs_designer
designer_view = {item["id"] for item in video_list("&view=designer")}
assert {card_a, card_b} <= designer_view and card_c not in designer_view

# Removed view names fall back to All.
for removed_view in ("pipeline-final", "no-overlay"):
    assert {item["id"] for item in video_list(f"&view={removed_view}")} == card_ids

# The card plays and downloads the no-overlay video with the approved title.
assert download_name(card_a) == "Approved A.mp4"
assert download_name(card_c) == "Approved C.mp4"
ranged = urllib.request.urlopen(urllib.request.Request(
    f"{BASE}/stream/{card_a}?type=video", headers={"Range": "bytes=0-99"},
), timeout=20)
assert ranged.status == 206 and ranged.read() == video_bytes[:100]

# A designer upload targets the no-overlay video. It inherits the approved
# title and becomes the active revision on the no-overlay row.
designer = upload("ignored-client-id", "video", title="Designer title", designer_of_id=card_a)
designer_id = designer["id"]
assert designer["ok"] and designer_id.startswith(f"{card_a}-designer-")
assert psql(
    f"SELECT designer_of_id || '|' || title FROM media_manager.files "
    f"WHERE id={literal(designer_id)} AND type='video'"
) == f"{card_a}|Approved A"
assert psql(
    f"SELECT active_designer_revision_id FROM media_manager.files "
    f"WHERE id={literal(card_a)} AND type='video'"
) == designer_id
assert psql(
    f"SELECT active_designer_revision_id FROM media_manager.files "
    f"WHERE id={literal(source_a)} AND type='video'"
) == legacy_active
assert download_name(designer_id) == "Approved A.mp4"

cards = video_list()
listed_a = card_for(cards, card_a)
assert listed_a["active_designer_revision_id"] == designer_id
assert listed_a["designer_video_id"] == designer_id
assert designer_id not in {item["id"] for item in cards}

# A second revision on a card without a legacy pointer becomes active too.
designer_c = upload("ignored-client-id", "video", title="Designer C", designer_of_id=card_c)
assert card_for(video_list(), card_c)["designer_video_id"] == designer_c["id"]
assert card_c not in {item["id"] for item in video_list("&view=needs-designer")}

# The overlaid video is no longer a designer target.
expect_http_error(400, lambda: request("/api/uploads/initiate", "POST", {
    "id": "ignored-client-id", "type": "video", "mime_type": "video/mp4",
    "file_size": len(video_bytes), "checksum_sha256": digest, "designer_of_id": source_a,
}))

print("isolated canonical card flow passed")
