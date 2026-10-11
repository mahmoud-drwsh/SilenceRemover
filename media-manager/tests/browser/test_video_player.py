"""Browser tests for the card downloads, the stream route, and the player page (#58).

The media is fixtures/clip.webm (10 s, 160x90, VP8 and Vorbis, a key frame
each second). Playwright's Chromium has no H.264 decoder, so the tests use
WebM and not the MP4 fixtures of the integration flows.
"""

import hashlib
import json
import pathlib
import re
import urllib.error
import urllib.request

from playwright.sync_api import expect

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
)

CLIP = (pathlib.Path(__file__).parent / "fixtures" / "clip.webm").read_bytes()
CLIP_SHA256 = hashlib.sha256(CLIP).hexdigest()
CSP_TEXT = "Content Security Policy"


def upload(project: str, file_id: str, media_type: str, **extra) -> dict:
    """Upload the clip through the public upload-session API."""
    status, _, session = api(project, "/uploads/initiate", "POST", {
        "id": file_id, "type": media_type, "mime_type": "video/webm",
        "file_size": len(CLIP), "checksum_sha256": CLIP_SHA256, **extra,
    })
    assert status == 200, (status, session)
    parts = []
    if session.get("part_size"):
        size = session["part_size"]
        for number, url in enumerate(session["urls"], start=1):
            if url.startswith("/"):
                url = APP + url
            chunk = CLIP[(number - 1) * size:number * size]
            with urllib.request.urlopen(urllib.request.Request(url, data=chunk, method="PUT"), timeout=30) as part:
                parts.append({"part_number": number, "etag": part.headers["ETag"]})
    else:
        request = urllib.request.Request(session["upload_url"], data=CLIP, method="PUT")
        urllib.request.urlopen(request, timeout=30).close()
    status, _, result = api(project, f"/uploads/{session['session_id']}/complete", "POST", {"parts": parts})
    assert status == 200 and result["ok"], (status, result)
    return result


def upload_card(project: str, source_id: str, title: str) -> str:
    """An original and its no-overlay video (the canonical card)."""
    upload(project, source_id, "original", original_filename=f"{source_id}.webm")
    result = upload(
        project, f"{source_id}-no-overlay", "video", title=title, tags=[], source_id=source_id,
        media_variant="no-overlay", visibility="active", publication_status="published",
    )
    return result["id"]


def make_designer_revision(project: str, card_id: str) -> str:
    """Upload a second card and turn its video row into the active designer
    revision of `card_id` (the designer upload route belongs to #61)."""
    other = upload_card(project, "rev-src", "Designer")
    psql(
        f"UPDATE {SCHEMA}.files SET designer_of_id={literal(card_id)}, media_variant='designer' "
        f"WHERE id={literal(other)} AND project={literal(project)} AND type='video'"
    )
    psql(
        f"UPDATE {SCHEMA}.files SET active_designer_revision_id={literal(other)} "
        f"WHERE id={literal(card_id)} AND project={literal(project)} AND type='video'"
    )
    return other


def stream(project: str, file_id: str, method: str = "GET", headers=None, file_type: str = "video"):
    """Call the stream route. Returns (status, headers, body bytes)."""
    url = f"{APP}/projects/{TOKEN}/{project}/stream/{file_id}?type={file_type}"
    request = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def player_path(file_id: str = "", title: str = "") -> str:
    query = []
    if file_id:
        query.append(f"file={urllib.request.quote(file_id)}")
    if title:
        query.append(f"title={urllib.request.quote(title)}")
    return "/video-player" + ("?" + "&".join(query) if query else "")


class StreamRouteTest(BrowserTestCase):
    """The HTTP behavior that the player and the downloads use."""

    def test_range_full_head_and_trash(self):
        project = new_project("stream")
        card = upload_card(project, "src-s", "Stream title")

        status, headers, body = stream(project, card, headers={"Range": "bytes=0-99"})
        self.assertEqual(status, 206)
        self.assertEqual(body, CLIP[:100])
        self.assertEqual(headers["Content-Range"], f"bytes 0-99/{len(CLIP)}")
        self.assertEqual(headers["Content-Length"], "100")
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(headers["Content-Type"], "video/webm")
        self.assertEqual(headers["Content-Disposition"], "inline; filename*=UTF-8''Stream%20title.webm")

        status, headers, body = stream(project, card, headers={"Range": "bytes=-10"})
        self.assertEqual((status, body), (206, CLIP[-10:]))

        status, headers, body = stream(project, card)
        self.assertEqual((status, body, headers["Content-Length"]), (200, CLIP, str(len(CLIP))))

        # A range that the object cannot satisfy gives the full 200 (not 416).
        status, _, body = stream(project, card, headers={"Range": f"bytes={len(CLIP) + 10}-"})
        self.assertEqual((status, body), (200, CLIP))

        # HEAD: the GET headers, with Content-Length 0 (the old service value).
        status, headers, body = stream(project, card, method="HEAD", headers={"Range": "bytes=0-99"})
        self.assertEqual((status, headers["Content-Range"], headers["Content-Length"], body),
                         (206, f"bytes 0-99/{len(CLIP)}", "0", b""))

        status, _, body = stream(project, card, file_type="subtitle")
        self.assertEqual((status, json.loads(body)), (400, {"detail": "Type parameter is required"}))

        # Trash the card with SQL (the update route belongs to #59).
        psql(f"UPDATE {SCHEMA}.files SET tags='[\"trash\"]'::jsonb, visibility='trash' "
             f"WHERE id={literal(card)} AND project={literal(project)} AND type='video'")
        status, _, body = stream(project, card)
        self.assertEqual((status, json.loads(body)), (404, {"detail": "File is in trash"}))


class CardDownloadsTest(BrowserTestCase):
    def test_three_downloads(self):
        project = new_project("downloads")
        card = upload_card(project, "src-a", "Approved A")
        revision = make_designer_revision(project, card)
        self.page.goto(project_url(project, "/videos"))
        card_locator = self.cards().filter(has_text="Approved A")
        expect(card_locator).to_have_count(1)
        downloads = card_locator.get_by_role("group", name="Downloads for Approved A")

        # Silence Removed: the no-overlay video, named with the card title.
        link = downloads.get_by_role("link", name=re.compile("Silence Removed"))
        expect(link).to_have_attribute("href", f"/projects/{TOKEN}/{project}/stream/{card}?type=video")
        with self.page.expect_download() as info:
            link.click()
        download = info.value
        self.assertEqual(download.suggested_filename, "Approved A.webm")
        self.assertEqual(pathlib.Path(download.path()).read_bytes(), CLIP)

        # Designer Video: the active revision, named with the card title.
        link = downloads.get_by_role("link", name=re.compile("Designer Video"))
        expect(link).to_contain_text("Active redesign")
        expect(link).to_have_attribute("href", f"/projects/{TOKEN}/{project}/stream/{revision}?type=video")
        with self.page.expect_download() as info:
            link.click()
        self.assertEqual(info.value.suggested_filename, "Approved A.webm")

        # Original: the API gives a presigned S3 URL; the browser downloads it.
        button = downloads.get_by_role("button", name=re.compile("Original"))
        expect(button).to_contain_text("Raw source")
        with self.page.expect_download() as info:
            with self.page.expect_response(re.compile(r"/api/originals/src-a/download$")) as response:
                button.click()
        self.assertEqual(response.value.status, 200)
        download = info.value
        self.assertEqual(download.suggested_filename, "Approved A.webm")
        self.assertEqual(pathlib.Path(download.path()).read_bytes(), CLIP)

    def test_unavailable_and_not_uploaded(self):
        project = new_project("missing")
        card = seed_card(project, "lonely-no-overlay", "Lonely card")
        psql(f"UPDATE {SCHEMA}.files SET source_id=NULL WHERE id={literal(card)} AND project={literal(project)}")
        self.page.goto(project_url(project, "/videos"))
        downloads = self.cards().filter(has_text="Lonely card").get_by_role("group", name="Downloads for Lonely card")
        original = downloads.get_by_role("button", name=re.compile("Original"))
        expect(original).to_contain_text("Unavailable")
        expect(original).to_be_disabled()
        designer = downloads.get_by_role("button", name=re.compile("Designer Video"))
        expect(designer).to_contain_text("Not uploaded")
        expect(designer).to_be_disabled()
        expect(downloads.get_by_role("link", name=re.compile("Silence Removed"))).to_be_visible()

    def test_trash_view_has_no_downloads(self):
        project = new_project("trashview")
        seed_card(project, "gone-no-overlay", "Gone card", visibility="trash", tags=["trash"])
        self.page.goto(project_url(project, "/videos/trash#admin"))
        card = self.cards().filter(has_text="Gone card")
        expect(card).to_have_count(1)
        expect(card.get_by_role("group")).to_have_count(0)
        expect(card.get_by_role("button", name="Play video")).to_have_count(0)


class VideoPlayerTest(BrowserTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.console: list[str] = []
        self.context.on("console", lambda message: self.console.append(message.text))

    def assert_no_csp_errors(self) -> None:
        self.assertEqual([text for text in self.console if CSP_TEXT in text], [])

    def wait_for_metadata(self, page) -> None:
        page.wait_for_function("() => { const v = document.querySelector('video'); return v && v.readyState >= 1; }")
        duration = page.evaluate("() => document.querySelector('video').duration")
        self.assertAlmostEqual(duration, 10, delta=0.5)

    def test_play_opens_player_in_new_tab_and_close_closes_it(self):
        project = new_project("player")
        card = upload_card(project, "src-p", "عنوان الفيديو")
        self.page.goto(project_url(project, "/videos"))
        with self.context.expect_page() as info:
            self.cards().first.get_by_role("button", name="Play video").click()
        player = info.value
        player.wait_for_load_state()
        self.assertIn(f"/projects/{TOKEN}/{project}/video-player?file={card}&title=", player.url)
        expect(player.get_by_role("heading", level=1)).to_have_text("عنوان الفيديو")
        expect(player.get_by_role("heading", level=1)).to_have_attribute("dir", "auto")
        self.wait_for_metadata(player)
        self.assert_no_csp_errors()
        # The card page stays where it was.
        self.assertTrue(self.page.url.endswith("/videos"))

        with player.expect_event("close"):
            player.get_by_role("button", name="Close").click()
        self.assertTrue(player.is_closed())

    def test_play_uses_same_tab_when_popup_is_blocked(self):
        project = new_project("popup")
        card = upload_card(project, "src-q", "Blocked popup")
        self.page.add_init_script("window.open = () => null;")
        self.page.goto(project_url(project, "/videos"))
        self.cards().first.get_by_role("button", name="Play video").click()
        self.page.wait_for_url(re.compile(rf"/video-player\?file={card}&title=Blocked%20popup$"))
        expect(self.page.get_by_role("heading", level=1)).to_have_text("Blocked popup")
        self.assertEqual(len(self.context.pages), 1)

    def test_seeking_uses_range_requests(self):
        project = new_project("seek")
        card = upload_card(project, "src-r", "Seek me")
        responses = []
        self.page.on("response", lambda r: responses.append(r) if "/stream/" in r.url else None)
        self.page.goto(project_url(project, player_path(card, "Seek me")))
        self.wait_for_metadata(self.page)

        # Seek with the time slider of the player: click at 75 %.
        slider = self.page.locator("[data-media-time-slider]").first
        expect(slider).to_be_visible()
        box = slider.bounding_box()
        self.page.mouse.click(box["x"] + box["width"] * 0.75, box["y"] + box["height"] / 2)
        self.page.wait_for_function(
            "() => { const v = document.querySelector('video');"
            " return v.currentTime > 5 && !v.seeking && v.readyState >= 2; }"
        )
        self.assertFalse(self.page.evaluate("() => document.querySelector('video').error !== null"))
        self.assertTrue(responses)
        for response in responses:
            self.assertEqual(response.status, 206)
            self.assertTrue(response.headers["content-range"].startswith("bytes "))
        self.assert_no_csp_errors()

    def test_close_goes_back_when_no_page_opened_the_player(self):
        project = new_project("back")
        card = upload_card(project, "src-b", "Go back")
        self.page.goto(project_url(project, "/videos"))
        expect(self.cards()).to_have_count(1)
        self.page.goto(project_url(project, player_path(card, "Go back")))
        self.page.get_by_role("button", name="Close").click()
        self.page.wait_for_url(re.compile(r"/videos$"))
        expect(self.cards()).to_have_count(1)

    def test_missing_id_message(self):
        project = new_project("noid")
        self.page.goto(project_url(project, "/video-player"))
        expect(self.page.get_by_role("heading", level=1)).to_have_text("Video Player")
        expect(self.page.locator("[data-slot=alert]")).to_have_text("Missing video id.")
        expect(self.page.locator("video")).to_have_count(0)

    def test_unplayable_video_message(self):
        project = new_project("broken")
        # A card row with no S3 object: the stream route gives 404.
        card = seed_card(project, "broken-no-overlay", "Broken card")
        self.page.goto(project_url(project, player_path(card, "Broken card")))
        expect(self.page.locator("[data-slot=alert]")).to_have_text("Unable to play this video.")

    def test_undecodable_video_message(self):
        project = new_project("garbage")
        card = upload_card(project, "src-g", "Garbage")
        # The stream answers with bytes that are not a video.
        self.page.route("**/stream/**", lambda route: route.fulfill(
            status=200, body=b"not a video" * 100, content_type="video/webm"))
        self.page.goto(project_url(project, player_path(card, "Garbage")))
        expect(self.page.locator("[data-slot=alert]")).to_have_text("Unable to play this video.")

    def test_bad_token_gives_error_page(self):
        response = self.page.goto(project_url(new_project(), player_path("x"), token="wrong-token"))
        self.assertEqual(response.status, 401)
        expect(self.page.locator("[data-slot=alert]")).to_contain_text("Invalid link")
