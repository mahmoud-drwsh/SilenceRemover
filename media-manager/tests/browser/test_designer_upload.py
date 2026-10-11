"""Browser tests for the designer upload dialog and designer revisions (#61).

The uploads are real (initiate, proxy part PUTs, complete) unless a test
replaces one response with page.route() to make an error or the
`already_uploaded` answer. The server never gives `already_uploaded` for a
designer upload (each upload gets a new revision ID), so that test injects it.
"""

import json
import re
import urllib.request

from playwright.sync_api import Request, Route, expect

from base import (
    APP,
    SCHEMA,
    TOKEN,
    BrowserTestCase,
    api,
    literal,
    new_project,
    project_url,
    psql,
    seed_card,
    seed_designer_revision,
)

PART_SIZE = 8 * 1024 * 1024
# The server sniffs the MIME type of the stored object: an "ftyp" box with
# the "isom" brand is video/mp4. ffprobe gives no duration (0) for the rest.
MP4_HEADER = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"


def video_bytes(size: int) -> bytes:
    return MP4_HEADER + bytes(size - len(MP4_HEADER))


def seed_original(project: str, source_id: str) -> None:
    psql(
        f"INSERT INTO {SCHEMA}.files (id, project, type, title, tags, duration, file_size, mime_type, "
        "created_at, source_id, original_filename) VALUES ("
        f"{literal(source_id)}, {literal(project)}, 'original', {literal(source_id + '.mp4')}, '[]'::jsonb, "
        f"75, 1536000, 'video/mp4', now(), {literal(source_id)}, {literal(source_id + '.mp4')})"
    )


def seed_upload_card(project: str, name: str, title: str) -> str:
    seed_original(project, name)
    return seed_card(project, f"{name}-no-overlay", title)


def card_state(project: str, card_id: str) -> dict:
    status, _, body = api(project, "/files?type=video")
    assert status == 200, body
    return next(item for item in body if item["id"] == card_id)


# Collect each status text and progress value of the open dialog in the page,
# so that a test can check the steps after a fast upload.
STATUS_LOG_SCRIPT = """
window.__designerLog = [];
new MutationObserver(() => {
  const dialog = document.querySelector('[data-slot=dialog-content]');
  if (!dialog) return;
  const status = dialog.querySelector('[role=status]');
  // The shadcn Progress gives the value only to the indicator position
  // (translateX(-<100 - value>%)), not to the ARIA attributes.
  const bar = dialog.querySelector('[data-slot=progress-indicator]');
  // The browser can write "translateX(-0%)" as "translateX(0%)" or "translateX(0px)".
  const match = bar ? /translateX\\((-?[0-9.]+)(%|px)\\)/.exec(bar.style.transform) : null;
  const entry = (status ? status.textContent : '') + '|' + (match ? String(100 + Number(match[1])) : bar ? 'raw:' + bar.style.transform : '');
  const log = window.__designerLog;
  if (log[log.length - 1] !== entry) log.push(entry);
}).observe(document, { subtree: true, childList: true, characterData: true, attributes: true });
"""


class DesignerUploadTest(BrowserTestCase):
    def open_card(self, project: str, card_id: str, path: str = "/videos"):
        self.page.goto(project_url(project, path))
        card = self.page.locator(f'[data-slot=card][data-id="{card_id}"]')
        expect(card).to_be_visible()
        return card

    def choose_file(self, size: int, name: str = "design.mp4") -> None:
        dialog = self.page.get_by_role("dialog")
        dialog.get_by_label("Redesigned video").set_input_files(
            {"name": name, "mimeType": "video/mp4", "buffer": video_bytes(size)},
        )

    def part_requests(self) -> list[Request]:
        parts: list[Request] = []
        self.page.on("request", lambda r: parts.append(r) if "/parts/" in r.url else None)
        return parts

    def test_first_upload_links_a_designer_video(self):
        project = new_project("designer")
        card_id = seed_upload_card(project, "first", "First approved title")
        card = self.open_card(project, card_id)
        parts = self.part_requests()

        card.get_by_role("button", name="Upload designer video").click()
        dialog = self.page.get_by_role("dialog")
        expect(dialog.get_by_role("heading", name="Upload designer video")).to_be_visible()
        expect(dialog).to_contain_text("Saving a new revision for: First approved title")
        title = dialog.get_by_label("Approved video title")
        expect(title).to_have_value("First approved title")
        expect(title).to_have_attribute("readonly", "")
        expect(dialog.get_by_label("Redesigned video")).to_have_attribute("accept", "video/*")

        self.choose_file(PART_SIZE + 1000)
        dialog.get_by_role("button", name="Upload and link").click()

        expect(dialog).to_be_hidden(timeout=60000)
        expect(self.page.locator("#app-status")).to_have_text("Designer revision uploaded successfully.")
        expect(card.get_by_role("button", name="Upload new revision")).to_be_visible()
        # Two parts through the same-origin proxy part route, in order.
        self.assertEqual([re.sub(r".*/parts/", "", r.url) for r in parts], ["1", "2"])
        state = card_state(project, card_id)
        revision = state["designer_video_id"]
        self.assertTrue(revision.startswith(f"{card_id}-designer-"))
        self.assertEqual(state["active_designer_revision_id"], revision)
        # The revision takes the approved title of the card, and is not a card.
        self.assertEqual(
            psql(f"SELECT designer_of_id || '|' || title || '|' || file_size FROM {SCHEMA}.files "
                 f"WHERE id={literal(revision)} AND project={literal(project)}"),
            f"{card_id}|First approved title|{PART_SIZE + 1000}",
        )
        self.assertEqual(self.cards().count(), 1)

    def test_new_revision_becomes_active(self):
        project = new_project("designer")
        card_id = seed_upload_card(project, "rev", "Revision title")
        old_revision = seed_designer_revision(project, card_id)
        card = self.open_card(project, card_id, "/videos/designer")
        self.assertEqual(card_state(project, card_id)["designer_video_id"], old_revision)

        card.get_by_role("button", name="Upload new revision").click()
        self.choose_file(4096)
        self.page.get_by_role("dialog").get_by_role("button", name="Upload and link").click()
        expect(self.page.get_by_role("dialog")).to_be_hidden(timeout=60000)
        expect(self.page.locator("#app-status")).to_have_text("Designer revision uploaded successfully.")

        state = card_state(project, card_id)
        self.assertNotEqual(state["designer_video_id"], old_revision)
        self.assertTrue(state["designer_video_id"].startswith(f"{card_id}-designer-"))
        self.assertEqual(state["active_designer_revision_id"], state["designer_video_id"])
        # The card's Designer Video download (#58) gives the newest revision.
        link = card.get_by_role("link", name=re.compile("Designer Video"))
        expect(link).to_have_attribute(
            "href", f"/projects/{TOKEN}/{project}/stream/{state['designer_video_id']}?type=video",
        )
        with urllib.request.urlopen(f"{APP}{link.get_attribute('href')}", timeout=30) as response:
            self.assertEqual(response.read(), video_bytes(4096))
            self.assertIn("Revision%20title.mp4", response.headers["Content-Disposition"])
        # The old revision stays (revisions are immutable).
        self.assertEqual(
            psql(f"SELECT count(*) FROM {SCHEMA}.files WHERE project={literal(project)} "
                 f"AND designer_of_id={literal(card_id)}"),
            "2",
        )

    def test_progress_display(self):
        project = new_project("designer")
        card_id = seed_upload_card(project, "progress", "Progress title")
        self.page.add_init_script(STATUS_LOG_SCRIPT)
        card = self.open_card(project, card_id)

        card.get_by_role("button", name="Upload designer video").click()
        self.choose_file(2 * PART_SIZE + 10)
        self.page.get_by_role("dialog").get_by_role("button", name="Upload and link").click()
        expect(self.page.get_by_role("dialog")).to_be_hidden(timeout=60000)

        log = self.page.evaluate("window.__designerLog")
        texts = [entry.split("|")[0] for entry in log]
        steps = [t for t in texts if t]
        expected = ["Preparing secure upload…", "Uploading 1/3…", "Uploading 2/3…", "Uploading 3/3…",
                    "Saving designer revision…"]
        self.assertEqual([t for t in dict.fromkeys(steps)], expected, log)
        # The progress bar goes from 0 to 100 percent.
        values = [entry.split("|")[1] for entry in log if entry.split("|")[1]]
        self.assertIn("0", values, log)
        self.assertIn("100", values, log)

    def test_upload_error_from_server(self):
        project = new_project("designer")
        # A card whose original is missing: the server refuses the initiate.
        card_id = seed_card(project, "orphan-no-overlay", "Orphan title")
        card = self.open_card(project, card_id)

        card.get_by_role("button", name="Upload designer video").click()
        self.choose_file(2048)
        dialog = self.page.get_by_role("dialog")
        dialog.get_by_role("button", name="Upload and link").click()
        alert = dialog.locator("[data-slot=alert]")
        expect(alert).to_contain_text("source_id must reference an available original in this project")
        # The dialog stays open, and the user can try again.
        expect(dialog.get_by_role("button", name="Upload and link")).to_be_enabled()
        self.assertIsNone(card_state(project, card_id)["designer_video_id"])

    def test_upload_error_from_part(self):
        project = new_project("designer")
        card_id = seed_upload_card(project, "part-error", "Part error title")
        card = self.open_card(project, card_id)
        self.page.route("**/parts/*", lambda route: route.fulfill(status=500, body="{}"))

        card.get_by_role("button", name="Upload designer video").click()
        self.choose_file(2048)
        dialog = self.page.get_by_role("dialog")
        dialog.get_by_role("button", name="Upload and link").click()
        expect(dialog.locator("[data-slot=alert]")).to_contain_text("Upload part 1 failed")
        expect(dialog.get_by_role("button", name="Upload and link")).to_be_enabled()

        # A second try after the fault goes away links the video.
        self.page.unroute("**/parts/*")
        dialog.get_by_role("button", name="Upload and link").click()
        expect(dialog).to_be_hidden(timeout=60000)
        self.assertIsNotNone(card_state(project, card_id)["designer_video_id"])

    def test_already_uploaded_stops_early(self):
        project = new_project("designer")
        card_id = seed_upload_card(project, "already", "Already title")
        card = self.open_card(project, card_id)
        calls: list[str] = []
        self.page.on("request", lambda r: calls.append(r.url) if "/api/" in r.url else None)
        initiate_bodies: list[dict] = []

        def already(route: Route) -> None:
            initiate_bodies.append(json.loads(route.request.post_data or "{}"))
            route.fulfill(status=200, content_type="application/json", body=json.dumps(
                {"ok": True, "id": f"{card_id}-designer", "type": "video", "already_uploaded": True},
            ))

        self.page.route("**/api/uploads/initiate", already)
        card.get_by_role("button", name="Upload designer video").click()
        self.choose_file(2048)
        calls.clear()
        self.page.get_by_role("dialog").get_by_role("button", name="Upload and link").click()

        expect(self.page.get_by_role("dialog")).to_be_hidden()
        expect(self.page.locator("#app-status")).to_have_text("Designer video was already uploaded.")
        expect(card).to_be_visible()
        self.page.wait_for_load_state("networkidle")
        # The request body is the old one: the checksum and designer_of_id.
        body = initiate_bodies[0]
        self.assertEqual(body["designer_of_id"], card_id)
        self.assertEqual(body["id"], f"{card_id}-designer")
        self.assertEqual(body["title"], "Already title")
        self.assertRegex(body["checksum_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(body["file_size"], 2048)
        # No part and no complete request; the list reloads.
        self.assertFalse([u for u in calls if "/parts/" in u or "/complete" in u], calls)
        self.assertTrue([u for u in calls if "/api/files?" in u], calls)

    def test_button_only_on_cards_outside_trash(self):
        project = new_project("designer")
        seed_upload_card(project, "trashed", "Trashed title")
        psql(f"UPDATE {SCHEMA}.files SET tags='[\"trash\"]'::jsonb, visibility='trash' "
             f"WHERE project={literal(project)} AND id='trashed-no-overlay'")
        card = self.open_card(project, "trashed-no-overlay", "/videos/trash#admin")
        expect(card.get_by_role("button", name=re.compile("Upload"))).to_have_count(0)
