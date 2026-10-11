"""Contract test: the real Python pipeline client against the Media Manager.

This flow runs the unchanged client from packages/sr_media_manager against
the service in the isolated stack (the current service or the new Next.js
app, spec #55). The client is the fixed side of the API contract. The flow
uses the upload functions of the client and only adds raw HTTP calls for
parts of the upload contract that the client cannot reach.

The pipeline client cannot upload derived media: `_upload_presigned` sends
no source_id, media_variant, visibility, or publication_status, so the
server rejects a derived upload by design. The worker uploads the derived
media (source-processing flow). This flow checks that rejection and the
`detail` text that the client shows.

Steps that need routes of later tickets of spec #55 run as "pending" when
their name is in CONTRACT_PENDING_STEPS (comma-separated). A pending step
that fails does not fail the flow. A pending step that passes prints a note,
so that you can remove it from the list. With the current service, the list
is empty and all steps must pass.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
import uuid
import wave
from pathlib import Path

import httpx

from sr_media_manager.api import MediaManagerClient, MediaManagerError

APP = "http://app:8080"
PROJECT = "client-contract"
BASE = f"{APP}/projects/test-token/{PROJECT}"
WORK = Path("/tmp/client-contract")
PENDING = {name.strip() for name in os.environ.get("CONTRACT_PENDING_STEPS", "").split(",") if name.strip()}
RUN = uuid.uuid4().hex[:8]


def psql(statement):
    result = subprocess.run(
        ["psql", "-h", "postgres", "-U", "media_manager", "-d", "media_manager",
         "-v", "ON_ERROR_STOP=1", "-At", "-c", statement],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


# Row tags as JSON text. Some writes keep the array as a JSON string in the
# jsonb column (an existing quirk that the read side accepts).
TAGS_TEXT = "(CASE WHEN jsonb_typeof(tags)='string' THEN (tags #>> '{}')::jsonb ELSE tags END)::text"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expect_error(text, call):
    """Run a client call that must raise MediaManagerError with `text` in it."""
    try:
        call()
    except MediaManagerError as error:
        assert text in str(error), f"expected {text!r} in {error}"
        return str(error)
    raise AssertionError(f"expected MediaManagerError with {text!r}")


class Recorder:
    """Record the API requests of the client (not the S3 PUT requests)."""

    def __init__(self, client):
        self.requests = []
        client._client.event_hooks["request"].append(self._record)

    def _record(self, request):
        try:
            body = request.content
        except httpx.RequestNotRead:
            body = b""  # A streamed multipart body (snippet analysis).
        self.requests.append((request.method, request.url.path, body))

    def clear(self):
        self.requests.clear()

    def calls(self, suffix):
        return [item for item in self.requests if item[1].endswith(suffix)]

    def session_ids(self, action):
        return [path.split("/")[-2] for _, path, _ in self.calls(f"/{action}")]


raw = httpx.Client(timeout=30.0)


def api(method, path, payload=None, expected=200):
    response = raw.request(method, BASE + path, json=payload)
    assert response.status_code == expected, f"{method} {path}: {response.status_code} {response.text}"
    return response.json()


def raw_initiate(file_id, media_type, data, mime, expected=200, **extra):
    return api("POST", "/api/uploads/initiate", {
        "id": file_id, "type": media_type, "mime_type": mime, "file_size": len(data),
        "checksum_sha256": hashlib.sha256(data).hexdigest(), **extra,
    }, expected)


def raw_put(session, data):
    if session.get("part_size"):
        parts = []
        for number, url in enumerate(session["urls"], start=1):
            start = (number - 1) * session["part_size"]
            response = httpx.put(url, content=data[start:start + session["part_size"]], timeout=60)
            response.raise_for_status()
            parts.append({"part_number": number, "etag": response.headers["etag"]})
        return parts
    response = httpx.put(session["upload_url"], content=data, timeout=60)
    response.raise_for_status()
    return []


results = []


def step(name, ticket=None):
    """Run a step. A step in CONTRACT_PENDING_STEPS may fail (later ticket)."""

    def decorator(function):
        pending = name in PENDING
        try:
            function()
        except Exception as error:
            if not pending:
                traceback.print_exc()
                results.append((name, "FAIL"))
                print(f"FAIL {name}: {error}", flush=True)
                return function
            results.append((name, f"pending ({ticket})"))
            print(f"PENDING {name} ({ticket}): fails as expected: {str(error)[:300]}", flush=True)
            return function
        if pending:
            results.append((name, f"pass (pending list, {ticket})"))
            print(f"NOTE {name} ({ticket}) passes now; remove it from CONTRACT_PENDING_STEPS", flush=True)
        else:
            results.append((name, "pass"))
            print(f"pass {name}", flush=True)
        return function

    return decorator


for _ in range(60):
    try:
        if raw.get(f"{APP}/healthz").status_code == 200:
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit("Media Manager did not become healthy")

WORK.mkdir(parents=True, exist_ok=True)
ORIGINAL = Path("/fixtures/original.mp4")
ORIGINAL_MKV = Path("/fixtures/original.mkv")
SRC = f"contract-src-{RUN}"
BIG = f"contract-big-{RUN}"
RESUME = f"contract-resume-{RUN}"
BAD = f"contract-bad-{RUN}"
NO_OVERLAY = f"{SRC}-no-overlay"

client = MediaManagerClient(f"{BASE}/")
recorder = Recorder(client)


def job_count(source_id):
    return int(psql(
        "SELECT count(*) FROM media_manager.source_processing "
        f"WHERE project={literal(PROJECT)} AND source_id={literal(source_id)}"
    ))


@step("upload_original: new original, one multipart part, queued for processing")
def _():
    recorder.clear()
    assert client.upload_original(SRC, ORIGINAL) is True
    (method, _, body), = recorder.calls("/complete")
    assert len(json.loads(body)["parts"]) == 1
    row = psql(
        "SELECT concat_ws('|', checksum_sha256, original_filename, file_size, mime_type) "
        f"FROM media_manager.files WHERE project={literal(PROJECT)} AND id={literal(SRC)} AND type='original'"
    )
    assert row == f"{sha256(ORIGINAL)}|original.mp4|{ORIGINAL.stat().st_size}|video/mp4", row
    state = psql(
        "SELECT state FROM media_manager.source_processing "
        f"WHERE project={literal(PROJECT)} AND source_id={literal(SRC)}"
    )
    assert state == "pending", state
    session_state = psql(
        f"SELECT state FROM media_manager.upload_sessions WHERE id={literal(recorder.session_ids('complete')[0])}"
    )
    assert session_state == "completed", session_state


@step("upload_original: identical original gives already_uploaded, no second job")
def _():
    recorder.clear()
    assert client.upload_original(SRC, ORIGINAL) is True
    assert not recorder.calls("/complete"), "an identical original must not open a session"
    result = client._upload_presigned(
        file_id=SRC, file_type="original", title=ORIGINAL.name, path=ORIGINAL, tags=[],
        original_filename=ORIGINAL.name,
    )
    assert result == {"ok": True, "id": SRC, "type": "original", "already_uploaded": True}, result
    assert job_count(SRC) == 1


@step("upload_original: different bytes for the same ID give the 409 detail")
def _():
    recorder.clear()
    message = expect_error(
        f"Original '{SRC}' already exists with different bytes",
        lambda: client.upload_original(SRC, ORIGINAL_MKV),
    )
    assert "409" in message, message
    assert not recorder.calls("/abort")


@step("upload_original: two multipart parts of 8 MiB")
def _():
    big = WORK / "big.mp4"
    big.write_bytes(ORIGINAL.read_bytes() + os.urandom(9 * 1024 * 1024))
    recorder.clear()
    assert client.upload_original(BIG, big) is True
    (_, _, body), = recorder.calls("/complete")
    parts = json.loads(body)["parts"]
    assert [part["part_number"] for part in parts] == [1, 2], parts
    row = psql(
        "SELECT concat_ws('|', checksum_sha256, file_size) FROM media_manager.files "
        f"WHERE project={literal(PROJECT)} AND id={literal(BIG)} AND type='original'"
    )
    assert row == f"{sha256(big)}|{big.stat().st_size}", row


@step("upload_original: resumes the active session with the same checksum")
def _():
    data = ORIGINAL.read_bytes()
    first = raw_initiate(RESUME, "original", data, "video/mp4", original_filename="original.mp4")
    recorder.clear()
    assert client.upload_original(RESUME, ORIGINAL) is True
    assert recorder.session_ids("complete") == [first["session_id"]], recorder.requests
    again = api("POST", f"/api/uploads/{first['session_id']}/complete", {"parts": []})
    assert again == {"ok": True, "id": RESUME, "type": "original", "already_completed": True}, again
    assert job_count(RESUME) == 1


@step("upload_original: a failed complete aborts the session and shows the detail")
def _():
    bad = WORK / "bad.mp4"
    bad.write_bytes(os.urandom(4096))
    recorder.clear()
    expect_error(
        "Uploaded object MIME type is invalid: expected original",
        lambda: client.upload_original(BAD, bad),
    )
    aborted = recorder.session_ids("abort")
    assert aborted == recorder.session_ids("complete") and len(aborted) == 1, recorder.requests
    state = psql(f"SELECT state FROM media_manager.upload_sessions WHERE id={literal(aborted[0])}")
    assert state == "aborted", state
    assert psql(f"SELECT count(*) FROM media_manager.files WHERE project={literal(PROJECT)} AND id={literal(BAD)}") == "0"


@step("upload_original: a 401 restarts the session once, then raises with the detail")
def _():
    bad_client = MediaManagerClient(f"{APP}/projects/wrong-token/{PROJECT}/")
    bad_recorder = Recorder(bad_client)
    expect_error("Invalid token", lambda: bad_client.upload_original(f"contract-auth-{RUN}", ORIGINAL))
    assert len(bad_recorder.calls("/api/uploads/initiate")) == 2, bad_recorder.requests


@step("_upload_presigned: derived audio is rejected (no source_id in the client)")
def _():
    wav = WORK / "review.wav"
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\0\0" * 8000)
    expect_error(
        "Derived media must include source_id for its original",
        lambda: client._upload_presigned(file_id=SRC, file_type="audio", title="t", path=wav, tags=[]),
    )


@step("_upload_presigned: derived video is rejected (no media attributes in the client)")
def _():
    expect_error(
        "Video uploads require explicit media_variant, visibility, and publication_status",
        lambda: client._upload_presigned(file_id=NO_OVERLAY, file_type="video", title="t", path=ORIGINAL, tags=[]),
    )


# Raw upload-contract checks that the client cannot reach.

@step("raw: bad checksum fails at complete with 400")
def _():
    data = ORIGINAL.read_bytes()
    session = api("POST", "/api/uploads/initiate", {
        "id": f"contract-badsum-{RUN}", "type": "original", "mime_type": "video/mp4",
        "file_size": len(data), "checksum_sha256": "0" * 64, "original_filename": "x.mp4",
    })
    parts = raw_put(session, data)
    result = api("POST", f"/api/uploads/{session['session_id']}/complete", {"parts": parts}, 400)
    assert result == {"detail": "Uploaded object verification failed: object checksum did not match request"}, result


@step("raw: no-overlay video with explicit attributes and source_id")
def _():
    data = ORIGINAL.read_bytes()
    session = raw_initiate(
        NO_OVERLAY, "video", data, "video/mp4", title="Contract", tags=[], source_id=SRC,
        media_variant="no-overlay", visibility="active", publication_status="published",
    )
    assert session["overwritten"] is False and len(session["urls"]) == 1, session
    result = api("POST", f"/api/uploads/{session['session_id']}/complete", {"parts": raw_put(session, data)})
    assert result == {"ok": True, "id": NO_OVERLAY, "type": "video", "overwritten": False}, result
    row = psql(
        "SELECT concat_ws('|', title, source_id, media_variant, visibility, publication_status, " + TAGS_TEXT + ") "
        f"FROM media_manager.files WHERE project={literal(PROJECT)} AND id={literal(NO_OVERLAY)} AND type='video'"
    )
    assert row == f"Contract|{SRC}|no-overlay|active|published|[]", row
    again = api("POST", f"/api/uploads/{session['session_id']}/complete", {"parts": []})
    assert again == {"ok": True, "id": NO_OVERLAY, "type": "video", "already_completed": True}, again


@step("raw: small audio uses one presigned PUT")
def _():
    data = (WORK / "review.wav").read_bytes()
    session = raw_initiate(SRC, "audio", data, "audio/wav", title="Audio title", source_id=SRC)
    assert "upload_url" in session and "urls" not in session and "part_size" not in session, session
    response = httpx.put(session["upload_url"], content=data, headers={"Content-Type": "audio/wav"}, timeout=60)
    response.raise_for_status()
    result = api("POST", f"/api/uploads/{session['session_id']}/complete", {})
    assert result == {"ok": True, "id": SRC, "type": "audio", "overwritten": False}, result
    row = psql(
        "SELECT concat_ws('|', review_status, source_id, " + TAGS_TEXT + ") FROM media_manager.files "
        f"WHERE project={literal(PROJECT)} AND id={literal(SRC)} AND type='audio'"
    )
    assert row == f"todo|{SRC}|[\"todo\"]", row


@step("raw: rejected initiate bodies")
def _():
    data = ORIGINAL.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    base = {"id": f"contract-reject-{RUN}", "mime_type": "video/mp4", "file_size": len(data), "checksum_sha256": digest}
    cases = [
        ({**base, "type": "subtitle"}, "Invalid type"),
        ({**base, "type": "video", "source_id": SRC, "media_variant": "pipeline-final",
          "visibility": "active", "publication_status": "published"}, "Invalid media_variant"),
        ({**base, "type": "video", "media_variant": "no-overlay", "visibility": "active",
          "publication_status": "published"}, "Derived media must include source_id for its original"),
        ({**base, "type": "video", "source_id": f"missing-{RUN}", "media_variant": "no-overlay",
          "visibility": "active", "publication_status": "published"},
         "source_id must reference an available original in this project"),
        ({**base, "type": "video", "designer_of_id": f"missing-{RUN}"},
         "designer_of_id must select an available no-overlay video in this project"),
        ({**base, "type": "original"}, "original_filename is required"),
        ({**base, "type": "original", "original_filename": "a.mp4", "checksum_sha256": "x"},
         "checksum_sha256 must be a SHA-256 hex digest"),
    ]
    for body, message in cases:
        result = api("POST", "/api/uploads/initiate", body, 400)
        assert result == {"detail": message}, (body, result)
    response = raw.post(BASE + "/api/uploads/initiate", content=b"not json")
    assert response.status_code == 400 and response.json() == {"detail": "JSON body is required"}, response.text


@step("raw: unknown session, abort, and token checks")
def _():
    assert api("POST", "/api/uploads/no-such-session/complete", {}, 404) == {"detail": "Upload session not found"}
    assert api("POST", "/api/uploads/no-such-session/abort") == {"ok": True}
    response = raw.post(f"{APP}/projects/wrong-token/{PROJECT}/api/uploads/initiate", json={})
    assert response.status_code == 401 and response.json() == {"detail": "Invalid token"}, response.text
    response = raw.post(f"{APP}/projects/wrong-token/{PROJECT}/api/uploads/x/abort")
    assert response.status_code == 401 and response.json() == {"detail": "Invalid token"}, response.text
    data = ORIGINAL.read_bytes()
    session = raw_initiate(f"contract-abort-{RUN}", "original", data, "video/mp4", original_filename="a.mp4")
    assert api("POST", f"/api/uploads/{session['session_id']}/abort") == {"ok": True}
    late = api("POST", f"/api/uploads/{session['session_id']}/complete", {"parts": []}, 409)
    assert late == {"detail": "Upload session is no longer active"}, late


@step("raw: the project name in the path arrives URL-decoded")
def _():
    data = ORIGINAL.read_bytes()
    project = f"client contract {RUN}"
    response = raw.post(f"{APP}/projects/test-token/client%20contract%20{RUN}/api/uploads/initiate", json={
        "id": f"contract-space-{RUN}", "type": "original", "mime_type": "video/mp4", "file_size": len(data),
        "checksum_sha256": hashlib.sha256(data).hexdigest(), "original_filename": "a.mp4",
    })
    assert response.status_code == 200, response.text
    stored = psql(f"SELECT project FROM media_manager.upload_sessions WHERE id={literal(response.json()['session_id'])}")
    assert stored == project, stored


# Client calls that need routes of later tickets (spec #55).

@step("get_original_files", "#57")
def _():
    rows = client.get_original_files()
    assert isinstance(rows, list)
    by_id = {row["id"]: row for row in rows}
    assert by_id[SRC]["checksum_sha256"] == sha256(ORIGINAL), by_id.get(SRC)
    assert BIG in by_id and BAD not in by_id


@step("analyze_ogg_snippet", "#62")
def _():
    snippet = WORK / "review.ogg"
    snippet.write_bytes(b"OggS" + b"client-contract-review-audio")
    transcript, title = client.analyze_ogg_snippet(snippet)
    assert transcript and title and "\n" not in title


@step("update_tags", "#59")
def _():
    assert client.update_tags(SRC, ["ready"], file_type="audio") is True
    tags = psql(
        f"SELECT {TAGS_TEXT} FROM media_manager.files "
        f"WHERE project={literal(PROJECT)} AND id={literal(SRC)} AND type='audio'"
    )
    assert tags == '["ready"]', tags
    expect_error("Tag update failed", lambda: client.update_tags(SRC, ["bogus"], file_type="audio"))


@step("delete_file", "#59")
def _():
    assert client.delete_file(BIG, file_type="original") is True
    assert psql(
        f"SELECT count(*) FROM media_manager.files WHERE project={literal(PROJECT)} AND id={literal(BIG)}"
    ) == "0"
    # Idempotent: the file is gone, so the trash step gets 404.
    assert client.delete_file(BIG, file_type="original") is True


client.close()
print("=== client contract results")
for name, outcome in results:
    print(f"{outcome}: {name}")
failed = [name for name, outcome in results if outcome == "FAIL"]
if failed:
    sys.exit(f"client contract failed: {failed}")
print("client contract flow passed")
