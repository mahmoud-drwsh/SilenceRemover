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
               active_pointer=None, created_at="now()", tags=(), visibility="active",
               publication_status="published"):
    """Insert a legacy video row with no S3 object."""
    psql(
        "INSERT INTO media_manager.files (id, project, type, title, tags, duration, file_size, "
        "mime_type, created_at, source_id, designer_of_id, active_designer_revision_id, "
        "media_variant, visibility, publication_status) VALUES ("
        f"{literal(file_id)}, {literal(PROJECT)}, 'video', {literal(title)}, "
        f"{literal(json.dumps(list(tags)))}::jsonb, 2, "
        f"{len(video_bytes)}, 'video/mp4', {created_at}, {literal(source_id)}, "
        f"{literal(designer_of_id)}, {literal(active_pointer)}, {literal(variant)}, "
        f"{literal(visibility)}, {literal(publication_status)})"
    )


def row_state(file_id):
    """Return title|visibility|publication_status|tags of a video row."""
    return psql(
        "SELECT concat_ws('|', title, visibility, publication_status, tags::text) "
        f"FROM media_manager.files WHERE id={literal(file_id)} AND type='video'"
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

# Legacy overlaid card state and title (#44 review findings 1, 2 and 7).
# Case D: the card has its own title; the legacy overlaid title does not win.
source_d = f"canonical-d-{run_id}"
card_d = upload_no_overlay(source_d, "Own D")
seed_video(source_d, "Old D", source_d, variant="pipeline-final")

# Case E: the overlaid card is in trash; its no-overlay companion is active.
source_e = f"canonical-e-{run_id}"
card_e = upload_no_overlay(source_e, "Approved E")
seed_video(source_e, "Approved E", source_e, variant="pipeline-final",
           tags=["trash"], visibility="trash")

# Case F: the overlaid card is pending.
source_f = f"canonical-f-{run_id}"
card_f = upload_no_overlay(source_f, "Approved F")
seed_video(source_f, "Approved F", source_f, variant="pipeline-final",
           publication_status="pending")

# Case G: the overlaid card is active; its no-overlay companion is in trash.
source_g = f"canonical-g-{run_id}"
card_g = upload_no_overlay(source_g, "Approved G")
seed_video(source_g, "Approved G", source_g, variant="pipeline-final")
psql(f"UPDATE media_manager.files SET tags='[\"trash\"]'::jsonb, visibility='trash' "
     f"WHERE id={literal(card_g)} AND type='video'")

cards = video_list()
card_ids = {item["id"] for item in cards}
assert card_for(cards, card_d)["title"] == "Own D"
assert card_e not in card_ids
assert card_for(cards, card_f)["publication_status"] == "pending"
listed_g = card_for(cards, card_g)
assert listed_g["visibility"] == "active", listed_g

trash_view = {item["id"]: item for item in video_list("&view=trash")}
assert card_e in trash_view and trash_view[card_e]["visibility"] == "trash"
assert card_g not in trash_view
assert card_e in {item["id"] for item in video_list("&include_trash=true")}
pending_view = {item["id"] for item in video_list("&view=pending")}
assert card_f in pending_view and card_d not in pending_view

# The count of a paged list uses the same filter as the rows.
paged = request("/api/files?type=video&limit=100&offset=0")
assert int(paged.headers["X-Total-Count"]) == len(json.load(paged)) == len(cards)

# The stream follows the card state.
expect_http_error(404, lambda: download_name(card_e))
assert download_name(card_g) == "Approved G.mp4"

# A designer upload needs an active card.
expect_http_error(400, lambda: request("/api/uploads/initiate", "POST", {
    "id": "ignored-client-id", "type": "video", "mime_type": "video/mp4",
    "file_size": len(video_bytes), "checksum_sha256": digest, "designer_of_id": card_e,
}))

# Write-through: trash, restore and title changes on the card also change the
# legacy overlaid row.
request(f"/api/files/{card_c}?type=video", "PUT", {"tags": ["trash"]}).read()
assert row_state(source_c) == 'Approved C|trash|published|["trash"]', row_state(source_c)
assert card_c in {item["id"] for item in video_list("&view=trash")}
assert card_c not in {item["id"] for item in video_list()}
request(f"/api/files/{card_c}?type=video", "PUT", {"tags": []}).read()
assert row_state(source_c) == "Approved C|active|published|[]", row_state(source_c)
assert card_c in {item["id"] for item in video_list()}

request(f"/api/files/{card_a}?type=video", "PUT", {"tags": [], "title": "Renamed A"}).read()
assert row_state(source_a).startswith("Renamed A|active|"), row_state(source_a)
assert card_for(video_list(), card_a)["title"] == "Renamed A"
assert download_name(card_a) == "Renamed A.mp4"

# Publish: the card state comes from the overlaid row, and the publish also
# changes the overlaid row.
request(f"/api/files/{card_f}/publish", "POST").read()
assert row_state(source_f) == "Approved F|active|published|[]", row_state(source_f)
assert card_f not in {item["id"] for item in video_list("&view=pending")}
expect_http_error(404, lambda: request(f"/api/files/{card_e}/publish", "POST"))

# Restore of a card that is in trash through its overlaid row.
request(f"/api/files/{card_e}?type=video", "PUT", {"tags": []}).read()
assert row_state(source_e) == "Approved E|active|published|[]", row_state(source_e)
assert card_e in {item["id"] for item in video_list()}

# Permanent delete follows the card state too: card G is active through its
# overlaid row, so the delete is refused.
expect_http_error(400, lambda: request(f"/api/files/{card_g}?type=video", "DELETE"))
request(f"/api/files/{card_e}?type=video", "PUT", {"tags": ["trash"]}).read()
assert json.load(request(f"/api/files/{card_e}?type=video", "DELETE"))["deleted"] is True

print("isolated canonical card flow passed")
