"""Verify that the no-overlay video is the canonical video card (#45, #51).

The flow uses the model after the #44 data move: each designer revision has
designer_of_id = `<source_id>-no-overlay`, and the active designer revision
pointer is on the no-overlay row. It seeds some rows with SQL, because the API
no longer makes them. It also seeds legacy rows (an overlaid video with
variant pipeline-final, and a `-designer` row without designer_of_id) and
checks that they have no effect on the card: no link, no title, no state.
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
    """Insert a video row with no S3 object."""
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

# Case A: two designer revisions link to the no-overlay card. With no active
# pointer, the newest revision shows on the card.
source_a = f"canonical-a-{run_id}"
card_a = upload_no_overlay(source_a, "Approved A")
older_a = f"{card_a}-designer-older"
newer_a = f"{card_a}-designer-newer"
seed_video(older_a, "Approved A", source_a, variant="designer", designer_of_id=card_a)
seed_video(newer_a, "Approved A", source_a, variant="designer", designer_of_id=card_a,
           created_at="now() + interval '1 hour'")

# Case B: the active pointer on the card wins over a newer revision.
source_b = f"canonical-b-{run_id}"
card_b = upload_no_overlay(source_b, "Approved B")
active_b = f"{card_b}-designer-active"
newer_b = f"{card_b}-designer-newer"
seed_video(active_b, "Approved B", source_b, variant="designer", designer_of_id=card_b)
seed_video(newer_b, "Approved B", source_b, variant="designer", designer_of_id=card_b,
           created_at="now() + interval '1 hour'")
psql(f"UPDATE media_manager.files SET active_designer_revision_id={literal(active_b)} "
     f"WHERE id={literal(card_b)} AND type='video'")

# Case C: legacy rows are not special. An overlaid row with a title, a trash
# state and an active pointer, a revision that links to the overlaid ID, and
# a legacy `-designer` row do not change the card.
source_c = f"canonical-c-{run_id}"
card_c = upload_no_overlay(source_c, "Approved C")
legacy_revision_c = f"{source_c}-designer-legacy"
seed_video(source_c, "Old C", source_c, variant="pipeline-final", tags=["trash"],
           visibility="trash", publication_status="pending", active_pointer=legacy_revision_c)
seed_video(legacy_revision_c, "Old C", source_c, variant="designer", designer_of_id=source_c)
seed_video(f"{source_c}-designer", "Old C", source_c)

# Case D: only a trashed revision. The card needs a designer, but the
# designer view shows it, because a revision exists.
source_d = f"canonical-d-{run_id}"
card_d = upload_no_overlay(source_d, "Approved D")
trashed_d = f"{card_d}-designer-trashed"
seed_video(trashed_d, "Approved D", source_d, variant="designer", designer_of_id=card_d,
           tags=["trash"], visibility="trash")

cards = video_list()
card_ids = {item["id"] for item in cards}
for removed in (source_c, legacy_revision_c, f"{source_c}-designer",
                older_a, newer_a, active_b, newer_b, trashed_d):
    assert removed not in card_ids, removed

listed_a = card_for(cards, card_a)
assert listed_a["media_variant"] == "no-overlay"
assert listed_a["source_id"] == source_a
assert listed_a["title"] == "Approved A"
assert listed_a["active_designer_revision_id"] is None
assert listed_a["designer_video_id"] == newer_a

listed_b = card_for(cards, card_b)
assert listed_b["active_designer_revision_id"] == active_b
assert listed_b["designer_video_id"] == active_b

listed_c = card_for(cards, card_c)
assert listed_c["title"] == "Approved C"
assert listed_c["visibility"] == "active"
assert listed_c["publication_status"] == "published"
assert listed_c["active_designer_revision_id"] is None
assert listed_c["designer_video_id"] is None

listed_d = card_for(cards, card_d)
assert listed_d["designer_video_id"] is None

needs_designer = {item["id"] for item in video_list("&view=needs-designer")}
assert {card_c, card_d} <= needs_designer
assert card_a not in needs_designer and card_b not in needs_designer
designer_missing = {item["id"] for item in video_list("&designer_missing=true")}
assert designer_missing == needs_designer
designer_view = {item["id"] for item in video_list("&view=designer")}
assert {card_a, card_b, card_d} <= designer_view and card_c not in designer_view
assert designer_view != card_ids

# Removed view names fall back to All.
for removed_view in ("pipeline-final", "no-overlay"):
    assert {item["id"] for item in video_list(f"&view={removed_view}")} == card_ids

# The card plays and downloads the no-overlay video with the card title.
assert download_name(card_a) == "Approved A.mp4"
assert download_name(card_c) == "Approved C.mp4"
ranged = urllib.request.urlopen(urllib.request.Request(
    f"{BASE}/stream/{card_a}?type=video", headers={"Range": "bytes=0-99"},
), timeout=20)
assert ranged.status == 206 and ranged.read() == video_bytes[:100]

# A designer upload targets the no-overlay video. It inherits the card title
# and becomes the active revision on the no-overlay row.
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
assert download_name(designer_id) == "Approved A.mp4"

cards = video_list()
listed_a = card_for(cards, card_a)
assert listed_a["active_designer_revision_id"] == designer_id
assert listed_a["designer_video_id"] == designer_id
assert designer_id not in {item["id"] for item in cards}

# A designer upload on the card with only legacy links. The upload takes the
# card title, not the legacy overlaid title.
designer_c = upload("ignored-client-id", "video", title="Designer C", designer_of_id=card_c)
assert card_for(video_list(), card_c)["designer_video_id"] == designer_c["id"]
assert card_c not in {item["id"] for item in video_list("&view=needs-designer")}
assert download_name(designer_c["id"]) == "Approved C.mp4"
assert psql(
    f"SELECT active_designer_revision_id FROM media_manager.files "
    f"WHERE id={literal(source_c)} AND type='video'"
) == legacy_revision_c

# The overlaid video is not a designer target.
expect_http_error(400, lambda: request("/api/uploads/initiate", "POST", {
    "id": "ignored-client-id", "type": "video", "mime_type": "video/mp4",
    "file_size": len(video_bytes), "checksum_sha256": digest, "designer_of_id": source_c,
}))

# Card state comes from the card row only.
# Case E: the card is in trash.
source_e = f"canonical-e-{run_id}"
card_e = upload_no_overlay(source_e, "Approved E")
request(f"/api/files/{card_e}?type=video", "PUT", {"tags": ["trash"]}).read()

# Case F: the card is pending.
source_f = f"canonical-f-{run_id}"
card_f = upload_no_overlay(source_f, "Approved F")
psql(f"UPDATE media_manager.files SET publication_status='pending' "
     f"WHERE id={literal(card_f)} AND type='video'")

cards = video_list()
card_ids = {item["id"] for item in cards}
assert card_e not in card_ids
assert card_for(cards, card_f)["publication_status"] == "pending"

trash_view = {item["id"]: item for item in video_list("&view=trash")}
assert card_e in trash_view and trash_view[card_e]["visibility"] == "trash"
assert card_c not in trash_view
assert card_e in {item["id"] for item in video_list("&include_trash=true")}
pending_view = {item["id"] for item in video_list("&view=pending")}
assert card_f in pending_view and card_c not in pending_view

# The count of a paged list uses the same filter as the rows, in each view.
for view_query in ("", "&view=needs-designer", "&view=designer", "&view=pending", "&view=trash"):
    paged = request(f"/api/files?type=video&limit=100&offset=0{view_query}")
    assert int(paged.headers["X-Total-Count"]) == len(json.load(paged)) == len(video_list(view_query)), view_query

# The stream follows the card state.
expect_http_error(404, lambda: download_name(card_e))

# A designer upload needs an active card.
expect_http_error(400, lambda: request("/api/uploads/initiate", "POST", {
    "id": "ignored-client-id", "type": "video", "mime_type": "video/mp4",
    "file_size": len(video_bytes), "checksum_sha256": digest, "designer_of_id": card_e,
}))

# Writes change only the card row, not the legacy overlaid row.
request(f"/api/files/{card_c}?type=video", "PUT", {"tags": [], "title": "Renamed C"}).read()
assert row_state(source_c) == 'Old C|trash|pending|["trash"]', row_state(source_c)
assert card_for(video_list(), card_c)["title"] == "Renamed C"
assert download_name(card_c) == "Renamed C.mp4"

request(f"/api/files/{card_f}/publish", "POST").read()
assert card_f not in {item["id"] for item in video_list("&view=pending")}
expect_http_error(404, lambda: request(f"/api/files/{card_e}/publish", "POST"))

# Restore and permanent delete use the card state.
request(f"/api/files/{card_e}?type=video", "PUT", {"tags": []}).read()
assert card_e in {item["id"] for item in video_list()}
expect_http_error(400, lambda: request(f"/api/files/{card_e}?type=video", "DELETE"))
request(f"/api/files/{card_e}?type=video", "PUT", {"tags": ["trash"]}).read()
assert json.load(request(f"/api/files/{card_e}?type=video", "DELETE"))["deleted"] is True

print("isolated canonical card flow passed")
