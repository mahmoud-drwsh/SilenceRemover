"""Browser tests for the admin dashboard (#63).

The admin token and the media token are global. Each test that changes them
puts back the test values (admin "test-admin-token", media "test-token"),
so that the other test files can use them.

All requests from this container come from one client IP. The rate-limit
tests send a different X-Forwarded-For value: the app trusts the rightmost
entry from an internal peer (in production that entry comes from Traefik),
so each value is a separate client. Thus a blocked test client does not
block the other tests.
"""

import json
import re
import urllib.error
import urllib.request
import uuid

from playwright.sync_api import expect

from base import (
    ADMIN_TOKEN,
    APP,
    BROWSER_APP,
    SCHEMA,
    TOKEN,
    BrowserTestCase,
    literal,
    new_project,
    psql,
)

ADMIN_TOKEN_SHA256 = "17d6bfe05d1b1fb7bc499f8e3f639c7b3eda4c40f321eef8887a0c04c89a99c5"


def admin_url(path: str = "/", token: str = ADMIN_TOKEN) -> str:
    return f"{BROWSER_APP}/admin/{token}{path}"


def admin_request(path: str, method: str = "GET", payload=None, token: str = ADMIN_TOKEN, client_ip: str | None = None):
    """Call an admin path. Returns (status, headers, body bytes)."""
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if client_ip:
        headers["X-Forwarded-For"] = client_ip
    request = urllib.request.Request(f"{APP}/admin/{token}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def fake_client_ip() -> str:
    """A new TEST-NET-3 address for each call (a separate rate-limit bucket)."""
    value = uuid.uuid4().int
    return f"203.0.{value % 250}.{(value >> 8) % 250 + 1}"


def restore_tokens() -> None:
    """Put back the test admin token and the test media token."""
    psql(f"UPDATE {SCHEMA}.auth_tokens SET token_hash = {literal(ADMIN_TOKEN_SHA256)} WHERE kind = 'admin'")
    status, _, _ = admin_request("/api/media-token", "POST", {"token": TOKEN})
    assert status == 200, status


def clear_media_token_copy() -> None:
    """The admin API returns no media token (as on a fresh database)."""
    psql(f"UPDATE {SCHEMA}.auth_tokens SET encrypted_token = NULL WHERE kind = 'media'")


def seed_admin_project() -> str:
    """A project with 3 audio rows (todo, ready, trash), 2 videos, 1536 bytes, updated 2 hours ago."""
    project = new_project("admin")
    rows = [
        ("a-todo", "audio", '["todo"]', 100),
        ("a-ready", "audio", '["ready"]', 200),
        ("a-trash", "audio", '["trash"]', 236),
        ("v-1-no-overlay", "video", "[]", 500),
        ("v-2-no-overlay", "video", '["trash"]', 500),
    ]
    values = ", ".join(
        f"({literal(file_id)}, {literal(project)}, {literal(kind)}, 'Title', {literal(tags)}::jsonb, {size}, "
        f"{literal('audio/ogg' if kind == 'audio' else 'video/mp4')}, now() - interval '2 hours')"
        for file_id, kind, tags, size in rows
    )
    psql(f"INSERT INTO {SCHEMA}.files (id, project, type, title, tags, file_size, mime_type, created_at) VALUES {values}")
    return project


def api_projects() -> list[dict]:
    status, _, body = admin_request("/api/projects")
    assert status == 200, status
    return json.loads(body)["projects"]


def format_bytes(value: int) -> str:
    if not value:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    number = float(value)
    while number >= 1024 and i < len(units) - 1:
        number /= 1024
        i += 1
    return f"{float(f'{number:.1f}'):g} {units[i]}"


class AdminDashboardTest(BrowserTestCase):
    def tearDown(self) -> None:
        super().tearDown()
        restore_tokens()

    def card(self, project: str):
        return self.page.locator(f'[data-slot=card][data-project="{project}"]')

    def stat(self, label: str):
        return self.page.locator(f'[data-stat="{label}"] dd')

    def test_statistics_and_project_card(self) -> None:
        project = seed_admin_project()
        clear_media_token_copy()
        release = {"s3": None}

        # Hold the S3 request, so that the "loading..." state is visible.
        def hold(route):
            release["s3"] = route

        self.page.route("**/api/projects/s3-storage", hold)
        self.page.goto(admin_url())
        expect(self.page).to_have_title("Media Manager Admin")
        expect(self.page.get_by_role("heading", name="Media Manager Admin")).to_be_visible()
        card = self.card(project)
        expect(card).to_be_visible()

        projects = api_projects()
        expect(self.stat("Projects")).to_have_text(str(len(projects)))
        expect(self.stat("Total Audio")).to_have_text(str(sum(p["audio"]["total"] for p in projects)))
        expect(self.stat("Total Video")).to_have_text(str(sum(p["video"]["total"] for p in projects)))
        expect(self.stat("DB Storage")).to_have_text(format_bytes(sum(p["storage_bytes"] for p in projects)))
        expect(self.stat("S3 Storage")).to_have_text("loading...")

        expect(card.get_by_role("heading", name=project)).to_be_visible()
        expect(card).to_contain_text("Audio: 3")
        for badge in ("1 todo", "1 ready", "1 trash"):
            expect(card.locator("[data-slot=badge]", has_text=badge)).to_be_visible()
        expect(card).to_contain_text("Video: 2")
        expect(card).to_contain_text("DB 1.5 KB • S3 loading... • 2 hours ago")

        # The S3 values come after the page.
        for _ in range(100):
            if release["s3"] is not None:
                break
            self.page.wait_for_timeout(50)
        self.assertIsNotNone(release["s3"])
        release["s3"].fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"projects": [{"project": project, "s3_storage_bytes": 3 * 1024 * 1024}],
                             "total_s3_storage_bytes": 5 * 1024 * 1024}),
        )
        expect(self.stat("S3 Storage")).to_have_text("5 MB")
        expect(card).to_contain_text("DB 1.5 KB • S3 3 MB • 2 hours ago")

        # Without a media token the links are disabled.
        for label in ("Open Audio", "Open Video"):
            button = card.get_by_role("button", name=f"{label} (set project token first)")
            expect(button).to_be_disabled()
        expect(card.get_by_role("link")).to_have_count(0)

    def test_s3_storage_unavailable(self) -> None:
        project = seed_admin_project()
        self.page.route("**/api/projects/s3-storage", lambda route: route.fulfill(status=500, body="{}"))
        self.page.goto(admin_url())
        expect(self.stat("S3 Storage")).to_have_text("unavailable")
        expect(self.card(project)).to_contain_text("S3 unavailable")

    def test_real_s3_storage_request(self) -> None:
        project = seed_admin_project()
        with self.page.expect_response(re.compile(r"/api/projects/s3-storage$")) as response_info:
            self.page.goto(admin_url())
        self.assertEqual(response_info.value.status, 200)
        expect(self.stat("S3 Storage")).not_to_have_text("loading...")
        expect(self.card(project)).to_contain_text("2 hours ago")

    def test_set_media_token_enables_links(self) -> None:
        project = seed_admin_project()
        clear_media_token_copy()
        self.page.goto(admin_url())
        card = self.card(project)
        expect(card.get_by_role("button", name="Open Audio (set project token first)")).to_be_disabled()

        self.page.get_by_role("button", name="Set Project Token", exact=True).click()
        expect(self.page.get_by_role("heading", name="Set project token")).to_be_visible()
        expect(self.page.get_by_text(
            "The token will be hashed for access checks and stored encrypted in Postgres for admin links.")).to_be_visible()
        field = self.page.get_by_placeholder("Paste the project/media token")
        field.fill(TOKEN)
        with self.page.expect_response(re.compile(r"/api/media-token$")) as response_info:
            self.page.get_by_role("button", name="Save token").click()
        self.assertEqual(response_info.value.status, 200)
        expect(self.page.get_by_role("heading", name="Set project token")).to_have_count(0)

        audio = card.get_by_role("link", name="Open Audio")
        video = card.get_by_role("link", name="Open Video")
        expect(audio).to_have_attribute("href", f"/projects/{TOKEN}/{project}/audio#admin")
        expect(video).to_have_attribute("href", f"/projects/{TOKEN}/{project}/videos#admin")
        expect(audio).to_have_attribute("target", "_blank")

        # The link opens the project in admin mode in a new tab.
        with self.context.expect_page() as popup_info:
            video.click()
        popup = popup_info.value
        popup.wait_for_load_state()
        self.assertTrue(popup.url.endswith(f"/projects/{TOKEN}/{project}/videos#admin"), popup.url)
        expect(popup.get_by_role("tab", name=re.compile("^Needs Designer"))).to_be_visible()

        # The stored token is the one that the API returns.
        status, _, body = admin_request("/api/projects")
        self.assertEqual(json.loads(body)["media_token"], TOKEN)

    def test_set_media_token_error(self) -> None:
        self.page.goto(admin_url())
        self.page.route("**/api/media-token", lambda route: route.fulfill(status=500, body="{}"))
        self.page.get_by_role("button", name="Set Project Token", exact=True).click()
        self.page.get_by_placeholder("Paste the project/media token").fill("some-token")
        self.page.get_by_role("button", name="Save token").click()
        expect(self.page.locator("[data-slot=alert]")).to_contain_text(
            "Error setting project token: HTTP 500: Internal Server Error")

    def test_refresh_admin_token(self) -> None:
        project = seed_admin_project()
        self.page.goto(admin_url())
        expect(self.card(project)).to_be_visible()
        with self.page.expect_response(re.compile(r"/api/refresh-admin-token$")) as response_info:
            self.page.get_by_role("button", name="Refresh Admin Token").click()
        new_token = response_info.value.json()["admin_token"]
        self.assertTrue(new_token.startswith("mm_admin_"))
        expect(self.page).to_have_url(admin_url("/", new_token))
        expect(self.card(project)).to_be_visible()

        # The old token stops at once; the new token works.
        self.assertEqual(admin_request("/api/projects")[0], 401)
        self.assertEqual(admin_request("/api/projects", token=new_token)[0], 200)
        # The page at the new URL loads.
        self.page.reload()
        expect(self.card(project)).to_be_visible()
        # An audit entry is written.
        self.assertGreaterEqual(int(psql(
            f"SELECT count(*) FROM {SCHEMA}.admin_audit_log WHERE action = 'refresh_admin_token'")), 1)

    def test_refresh_admin_token_error(self) -> None:
        self.page.goto(admin_url())
        self.page.route("**/api/refresh-admin-token", lambda route: route.fulfill(status=503, body="{}"))
        self.page.get_by_role("button", name="Refresh Admin Token").click()
        expect(self.page.locator("[data-slot=alert]")).to_contain_text(
            "Error refreshing admin token: HTTP 503: Service Unavailable")
        expect(self.page).to_have_url(admin_url())

    def test_refresh_reloads_the_list(self) -> None:
        project = seed_admin_project()
        self.page.goto(admin_url())
        card = self.card(project)
        expect(card).to_contain_text("Audio: 3")
        psql(
            f"INSERT INTO {SCHEMA}.files (id, project, type, title, tags, file_size, mime_type) VALUES "
            f"('a-new', {literal(project)}, 'audio', 'New', '[\"todo\"]'::jsonb, 0, 'audio/ogg')"
        )
        self.page.get_by_role("button", name="Refresh", exact=True).click()
        expect(card).to_contain_text("Audio: 4")
        expect(card.locator("[data-slot=badge]", has_text="2 todo")).to_be_visible()
        expect(card).to_contain_text("Just now")

    def test_no_projects_found(self) -> None:
        self.page.route("**/api/projects", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"media_token": null, "projects": []}'))
        self.page.goto(admin_url())
        expect(self.page.get_by_text("No projects found")).to_be_visible()

    def test_project_list_errors(self) -> None:
        self.page.route("**/api/projects", lambda route: route.fulfill(status=401, body="{}"))
        self.page.goto(admin_url())
        expect(self.page.locator("[data-slot=alert]")).to_contain_text("Error: Invalid admin token")
        self.page.unroute("**/api/projects")
        self.page.route("**/api/projects", lambda route: route.fulfill(status=503, body="{}"))
        self.page.get_by_role("button", name="Refresh", exact=True).click()
        expect(self.page.locator("[data-slot=alert]")).to_contain_text("Error: HTTP 503: Service Unavailable")

    def test_invalid_admin_token_page(self) -> None:
        response = self.page.goto(admin_url("/", "not-the-admin-token"))
        self.assertEqual(response.status, 401)
        expect(self.page.locator("[data-slot=alert]")).to_contain_text("Invalid admin token")
        expect(self.page.get_by_role("heading", name="Media Manager Admin")).to_have_count(0)
        # A good token afterwards clears the counter of this client.
        self.assertEqual(self.page.goto(admin_url()).status, 200)

    def test_old_catch_all_paths_show_the_dashboard(self) -> None:
        project = seed_admin_project()
        for path in ("", "/", "/api/unknown", "/api/refresh-token", "/api/projects/", "/x/y"):
            response = self.page.goto(admin_url(path))
            self.assertEqual(response.status, 200, path)
            expect(self.card(project)).to_be_visible()
        # Another method on a page path gets the JSON 404 (no page, no server action).
        for path in ("/", "/api/unknown", "/x"):
            status, headers, body = admin_request(path, "POST", {})
            self.assertEqual((status, json.loads(body)), (404, {"detail": "Not Found"}), path)
        # The removed File Browser keeps its own answer.
        status, _, body = admin_request("/files", "POST", {})
        self.assertEqual((status, json.loads(body)), (404, {"detail": "Admin File Browser has been removed"}))


class AdminRateLimitTest(BrowserTestCase):
    def test_page_rate_limit_for_one_client(self) -> None:
        client = fake_client_ip()
        for attempt in range(8):
            status, _, _ = admin_request("/", token="wrong-token", client_ip=client)
            self.assertEqual(status, 401, attempt)
        status, headers, body = admin_request("/", token="wrong-token", client_ip=client)
        self.assertEqual(status, 429)
        self.assertEqual(json.loads(body), {"detail": "Too many admin login attempts. Try again later."})
        self.assertGreaterEqual(int(headers["Retry-After"]), 1)
        # The good token is also refused for this client (the limit comes first).
        self.assertEqual(admin_request("/", client_ip=client)[0], 429)
        self.assertEqual(admin_request("/api/projects", client_ip=client)[0], 429)
        # Another client is not blocked.
        self.assertEqual(admin_request("/", token="wrong-token", client_ip=fake_client_ip())[0], 401)
        self.assertEqual(admin_request("/")[0], 200)

        # The browser sees the 429 for the blocked client.
        context = self.browser.new_context(extra_http_headers={"X-Forwarded-For": client})
        try:
            response = context.new_page().goto(admin_url())
            self.assertEqual(response.status, 429)
            self.assertIsNotNone(response.header_value("retry-after"))
        finally:
            context.close()

    def test_api_failures_count_for_the_page(self) -> None:
        client = fake_client_ip()
        for _ in range(8):
            self.assertEqual(admin_request("/api/projects", token="wrong-token", client_ip=client)[0], 401)
        status, headers, _ = admin_request("/", client_ip=client)
        self.assertEqual(status, 429)
        self.assertIn("Retry-After", headers)
