"""Shared helpers for the browser tests (Playwright for Python, stdlib unittest).

The tests run in the isolated Docker Compose stack against the app service
(MM_BASE_URL, default http://app:8080). Run them with:

  MM_APP=next SRFRESH_TAG=<tag> flock ~/.claude/jobs/fbb14f0c/tmp/docker.lock \
    remote-js/tests/integration/run_isolated_fresh.sh browser

Add a test: make a file test_<area>.py in this folder with a class that
extends BrowserTestCase. Each test gets a new browser context and page
(`self.page`). Use a new project name (`new_project()`) for each test, so
that the tests do not change the data of the other tests. Seed data through
the public HTTP API (`api()`), or with SQL (`psql()`, `seed_card()`) for
rows that the API does not make.
"""

import hashlib
import io
import json
import math
import os
import socket
import subprocess
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

APP = os.environ.get("MM_BASE_URL", "http://app:8080")
# The browser uses another host name for the app. "app" is a top-level
# domain on the HSTS preload list, so Chromium sends every request to
# http://app:8080 as HTTPS. A ".test" name (RFC 2606) is not on the list;
# the browser maps it to the address of the app service.
BROWSER_HOST = "media-manager.test"
_app_host = urllib.parse.urlsplit(APP)
BROWSER_APP = APP.replace(f"//{_app_host.hostname}", f"//{BROWSER_HOST}", 1)
TOKEN = "test-token"
ADMIN_TOKEN = "test-admin-token"
SCHEMA = "media_manager"


def wait_until_healthy(timeout_sec: int = 90) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            if urllib.request.urlopen(f"{APP}/healthz", timeout=5).status == 200:
                return
        except Exception:
            time.sleep(1)
    raise SystemExit("Media Manager did not become healthy")


def new_project(prefix: str = "browser") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def project_url(project: str, path: str = "", token: str = TOKEN) -> str:
    """A project page URL for the browser."""
    return f"{BROWSER_APP}/projects/{token}/{project}{path}"


def api(project: str, path: str, method: str = "GET", payload=None, token: str = TOKEN):
    """Call the project API. Returns (status, headers, parsed JSON body)."""
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    url = f"{APP}/projects/{token}/{project}/api{path}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.headers, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, error.headers, json.loads(error.read() or b"null")


def psql(statement: str) -> str:
    result = subprocess.run(
        ["psql", "-h", "postgres", "-U", "media_manager", "-d", "media_manager",
         "-v", "ON_ERROR_STOP=1", "-At", "-c", statement],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def literal(value) -> str:
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


def seed_card(project: str, card_id: str, title: str, *, publication_status: str = "published",
              visibility: str = "active", tags=(), duration: float = 75, file_size: int = 1536000) -> str:
    """Insert a canonical video card (a no-overlay video row, no S3 object)."""
    psql(
        f"INSERT INTO {SCHEMA}.files (id, project, type, title, tags, duration, file_size, mime_type, "
        "created_at, source_id, media_variant, visibility, publication_status) VALUES ("
        f"{literal(card_id)}, {literal(project)}, 'video', {literal(title)}, "
        f"{literal(json.dumps(list(tags)))}::jsonb, {duration}, {file_size}, 'video/mp4', now(), "
        f"{literal(card_id.removesuffix('-no-overlay'))}, 'no-overlay', {literal(visibility)}, "
        f"{literal(publication_status)})"
    )
    return card_id


def seed_designer_revision(project: str, card_id: str, *, active: bool = True) -> str:
    """Insert a designer revision of a card, and make it active when asked."""
    revision_id = f"{card_id}-designer-{uuid.uuid4().hex[:8]}"
    psql(
        f"INSERT INTO {SCHEMA}.files (id, project, type, title, tags, duration, file_size, mime_type, "
        "created_at, source_id, designer_of_id, media_variant, visibility, publication_status) VALUES ("
        f"{literal(revision_id)}, {literal(project)}, 'video', 'Designer', '[]'::jsonb, 75, 1536000, "
        f"'video/mp4', now(), {literal(card_id.removesuffix('-no-overlay'))}, {literal(card_id)}, "
        "'designer', 'active', 'published')"
    )
    if active:
        psql(
            f"UPDATE {SCHEMA}.files SET active_designer_revision_id={literal(revision_id)} "
            f"WHERE id={literal(card_id)} AND project={literal(project)} AND type='video'"
        )
    return revision_id


def seed_many_cards(project: str, count: int, prefix: str = "card") -> list[str]:
    """Insert `count` cards named <prefix>-00001-no-overlay ... in one statement."""
    psql(
        f"INSERT INTO {SCHEMA}.files (id, project, type, title, tags, duration, file_size, mime_type, "
        "created_at, source_id, media_variant, visibility, publication_status) "
        f"SELECT format('{prefix}-%s-no-overlay', lpad(i::text, 5, '0')), {literal(project)}, 'video', "
        f"format('Video %s', i), '[]'::jsonb, 60, 1048576, 'video/mp4', now(), "
        f"format('{prefix}-%s', lpad(i::text, 5, '0')), 'no-overlay', 'active', 'published' "
        f"FROM generate_series(1, {count}) AS i"
    )
    return [f"{prefix}-{i:05d}-no-overlay" for i in range(1, count + 1)]


def seed_audio(project: str, audio_id: str, title: str | None, *, tags=("todo",),
               review_status: str = "todo", visibility: str = "active") -> str:
    """Insert a review audio row (no S3 object)."""
    psql(
        f"INSERT INTO {SCHEMA}.files (id, project, type, title, tags, duration, file_size, mime_type, "
        "created_at, source_id, review_status, visibility) VALUES ("
        f"{literal(audio_id)}, {literal(project)}, 'audio', {literal(title)}, "
        f"{literal(json.dumps(list(tags)))}::jsonb, 12, 192000, 'audio/wav', now(), "
        f"{literal(audio_id)}, {literal(review_status)}, {literal(visibility)})"
    )
    return audio_id


def file_row(project: str, file_id: str, file_type: str) -> dict | None:
    """The tags, title, review_status, and visibility of a row, or None."""
    out = psql(
        f"SELECT json_build_object('tags', tags, 'title', title, 'review_status', review_status, "
        f"'visibility', visibility) FROM {SCHEMA}.files WHERE project={literal(project)} "
        f"AND id={literal(file_id)} AND type={literal(file_type)}"
    )
    return json.loads(out) if out else None


def wav_bytes(seconds: float = 3.0, rate: int = 8000, frequency: float = 440.0) -> bytes:
    """A mono 16-bit PCM WAV with a sine tone (Chromium plays PCM WAV; it has no AAC)."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            value = int(12000 * math.sin(2 * math.pi * frequency * i / rate))
            frames += value.to_bytes(2, "little", signed=True)
        out.writeframes(bytes(frames))
    return buffer.getvalue()


def upload_audio(project: str, audio_id: str, title: str) -> str:
    """Upload a WAV review audio through the upload session API (with an S3 object).

    The audio needs an original row (source_id), so the helper inserts one.
    """
    psql(
        f"INSERT INTO {SCHEMA}.files (id, project, type, title, tags, duration, file_size, mime_type, "
        f"created_at, original_filename) VALUES ({literal(audio_id)}, {literal(project)}, 'original', "
        f"{literal(audio_id)}, '[]'::jsonb, 3, 1, 'video/mp4', now(), 'source.mp4')"
    )
    data = wav_bytes()
    status, _, session = api(project, "/uploads/initiate", "POST", {
        "id": audio_id, "type": "audio", "title": title, "mime_type": "audio/wav",
        "file_size": len(data), "checksum_sha256": hashlib.sha256(data).hexdigest(),
        "source_id": audio_id, "tags": ["todo"],
    })
    if status != 200:
        raise AssertionError(f"initiate failed: {status} {session}")
    put = urllib.request.Request(session["upload_url"], data=data, method="PUT",
                                 headers={"Content-Type": "audio/wav"})
    urllib.request.urlopen(put, timeout=30).close()
    status, _, body = api(project, f"/uploads/{session['session_id']}/complete", "POST", {})
    if status != 200:
        raise AssertionError(f"complete failed: {status} {body}")
    return audio_id


class BrowserTestCase(unittest.TestCase):
    """One Chromium for each test class, one context and page for each test."""

    playwright: Playwright
    browser: Browser
    page: Page

    @classmethod
    def setUpClass(cls) -> None:
        wait_until_healthy()
        cls.playwright = sync_playwright().start()
        address = socket.gethostbyname(_app_host.hostname or "app")
        cls.browser = cls.playwright.chromium.launch(
            args=[f"--host-resolver-rules=MAP {BROWSER_HOST} {address}"],
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self) -> None:
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 720})
        self.context.set_default_timeout(15000)
        self.page = self.context.new_page()

    def tearDown(self) -> None:
        self.context.close()

    def cards(self):
        """The media cards of the current list."""
        return self.page.locator("[data-slot=card][data-id]")
