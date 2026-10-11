"""Browser tests for the project page: token gate, video views, paging, roles (#57)."""

import re

from playwright.sync_api import Route, expect

from base import (
    BrowserTestCase,
    api,
    new_project,
    project_url,
    seed_card,
    seed_designer_revision,
    seed_many_cards,
)


def seed_views_project() -> tuple[str, dict[str, str]]:
    """A project with one card for each state.

    plain   -> All, Needs Designer
    linked  -> All, Designer Video (active designer revision)
    pending -> All, Needs Designer, Pending
    trashed -> Trash only
    """
    project = new_project("views")
    cards = {
        "plain": seed_card(project, "a-plain-no-overlay", "Plain card"),
        "linked": seed_card(project, "b-linked-no-overlay", "Linked card"),
        "pending": seed_card(project, "c-pending-no-overlay", "Pending card", publication_status="pending"),
        "trashed": seed_card(project, "d-trashed-no-overlay", "Trashed card", visibility="trash", tags=["trash"]),
    }
    seed_designer_revision(project, cards["linked"])
    return project, cards


EXPECTED_VIEWS = [
    # (tab label, URL path, expected card ids)
    ("All", "/videos", ["plain", "linked", "pending"]),
    ("Needs Designer", "/videos/needs-designer", ["plain", "pending"]),
    ("Designer Video", "/videos/designer", ["linked"]),
    ("Pending", "/videos/pending", ["pending"]),
    ("Trash", "/videos/trash", ["trashed"]),
]


class TokenGateTest(BrowserTestCase):
    def test_bad_token_gives_error_page_and_api_401(self):
        project = new_project()
        response = self.page.goto(project_url(project, "/videos", token="wrong-token"))
        self.assertEqual(response.status, 401)
        self.assertIn("text/html", response.headers["content-type"])
        alert = self.page.locator("[data-slot=alert]")
        expect(alert).to_contain_text("Invalid link")
        # The error page uses the root layout and the app stylesheet
        # (rounded-lg = 10 px), not an unstyled fallback page.
        expect(self.page.locator("html")).to_have_attribute("lang", "en")
        expect(alert).to_have_css("border-top-left-radius", "10px")

        status, _, body = api(project, "/files?type=video", token="wrong-token")
        self.assertEqual(status, 401)
        self.assertEqual(body, {"detail": "Invalid token"})

    def test_good_token_opens_page_with_and_without_trailing_slash(self):
        project = new_project()
        for path in ("", "/"):
            response = self.page.goto(project_url(project, path))
            self.assertEqual(response.status, 200)
            expect(self.page.get_by_role("heading", level=1)).to_have_text("TODO (0)")

    def test_unknown_api_path_is_json_404(self):
        project = new_project()
        status, headers, body = api(project, "/no-such-route")
        self.assertEqual((status, body), (404, {"detail": "Not Found"}))
        self.assertIn("application/json", headers["Content-Type"])


class VideoViewsTest(BrowserTestCase):
    def test_each_view_shows_its_cards_and_count(self):
        project, cards = seed_views_project()
        self.page.goto(project_url(project, "/videos#admin"))
        for label, path, expected in EXPECTED_VIEWS:
            with self.subTest(view=label):
                self.page.get_by_role("tab", name=label, exact=True).click()
                expect(self.page.get_by_role("heading", level=1)).to_have_text(f"{label} ({len(expected)})")
                expect(self.cards()).to_have_count(len(expected))
                ids = self.cards().evaluate_all("els => els.map(e => e.dataset.id)")
                self.assertEqual(ids, [cards[key] for key in expected])
                expect(self.page).to_have_url(re.compile(re.escape(path) + "#admin$"))

    def test_card_shows_title_duration_size_and_id(self):
        project, cards = seed_views_project()
        self.page.goto(project_url(project, "/videos#admin"))
        card = self.page.locator(f"[data-id='{cards['plain']}']")
        expect(card.get_by_role("heading", level=2)).to_have_text("Plain card")
        expect(card).to_contain_text(f"1:15 • 1.5 MB • {cards['plain']}")

    def test_empty_view_shows_empty_state(self):
        project = new_project("empty")
        self.page.goto(project_url(project, "/videos#admin"))
        expect(self.page.get_by_role("heading", level=1)).to_have_text("All (0)")
        expect(self.page.get_by_text("No video files in this view")).to_be_visible()
        expect(self.cards()).to_have_count(0)

    def test_removed_view_names_open_all(self):
        project, _ = seed_views_project()
        for removed in ("pipeline-final", "no-overlay"):
            with self.subTest(view=removed):
                self.page.goto(project_url(project, f"/videos/{removed}#admin"))
                expect(self.page.get_by_role("heading", level=1)).to_have_text("All (3)")
                expect(self.page.get_by_role("tab", name="All", exact=True)).to_have_attribute("aria-selected", "true")

    def test_phone_width_has_no_horizontal_scroll(self):
        project, _ = seed_views_project()
        self.page.set_viewport_size({"width": 360, "height": 740})
        self.page.goto(project_url(project, "/videos#admin"))
        expect(self.page.get_by_role("heading", level=1)).to_have_text("All (3)")
        overflow = self.page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        self.assertLessEqual(overflow, 0)

    def test_old_responses_are_ignored(self):
        project, cards = seed_views_project()
        held: list[Route] = []
        self.page.route("**/api/files?*view=needs-designer*", lambda route: held.append(route))
        self.page.goto(project_url(project, "/videos#admin"))
        expect(self.page.get_by_role("heading", level=1)).to_have_text("All (3)")
        self.page.get_by_role("tab", name="Needs Designer", exact=True).click()
        for _ in range(50):
            if held:
                break
            self.page.wait_for_timeout(100)
        self.assertTrue(held, "the Needs Designer request did not start")
        self.page.get_by_role("tab", name="Designer Video", exact=True).click()
        expect(self.page.get_by_role("heading", level=1)).to_have_text("Designer Video (1)")
        # The old request answers last. Its result must not replace the list.
        for route in held:
            try:
                route.continue_()
            except Exception:
                pass  # The page cancelled the request.
        self.page.wait_for_timeout(500)
        expect(self.page.get_by_role("heading", level=1)).to_have_text("Designer Video (1)")
        ids = self.cards().evaluate_all("els => els.map(e => e.dataset.id)")
        self.assertEqual(ids, [cards["linked"]])


class PagingTest(BrowserTestCase):
    def open_large_project(self):
        project = new_project("paging")
        ids = seed_many_cards(project, 30)
        requests: list[str] = []
        self.page.on("request", lambda request: requests.append(request.url) if "/api/files?" in request.url else None)
        return project, ids, requests

    def test_load_more_runs_near_the_end_and_uses_prefetch(self):
        project, ids, requests = self.open_large_project()
        self.page.goto(project_url(project, "/videos#admin"))
        expect(self.page.get_by_role("heading", level=1)).to_have_text("All (30)")
        expect(self.cards()).to_have_count(24)
        # The next page is prefetched before the user scrolls.
        self.page.wait_for_function(
            "() => performance.getEntriesByType('resource').some(e => e.name.includes('offset=24'))")
        prefetches = [url for url in requests if "offset=24" in url]
        self.assertEqual(len(prefetches), 1)
        self.assertIn("limit=24", prefetches[0])
        self.page.mouse.wheel(0, 20000)
        expect(self.cards()).to_have_count(30)
        expect(self.page.get_by_role("button", name="Load more")).to_have_count(0)
        # The scroll used the prefetched page; it did not fetch it again.
        self.assertEqual(len([url for url in requests if "offset=24" in url]), 1)
        ids_on_page = self.cards().evaluate_all("els => els.map(e => e.dataset.id)")
        self.assertEqual(ids_on_page, ids)

    def test_retry_button_after_a_load_error(self):
        project, ids, _ = self.open_large_project()
        failing = "**/api/files?*offset=24*"
        self.page.route(failing, lambda route: route.fulfill(status=500, body="fail"))
        self.page.goto(project_url(project, "/videos#admin"))
        expect(self.cards()).to_have_count(24)
        self.page.mouse.wheel(0, 20000)
        retry = self.page.get_by_role("button", name="Retry loading more: HTTP 500: Internal Server Error")
        expect(retry).to_be_visible()
        expect(self.cards()).to_have_count(24)
        self.page.unroute(failing)
        retry.click()
        expect(self.cards()).to_have_count(30)
        self.assertEqual(self.cards().evaluate_all("els => els.map(e => e.dataset.id)"), ids)

    def test_retry_button_after_a_first_page_error(self):
        project, _, _ = self.open_large_project()
        failing = "**/api/files?*offset=0*"
        self.page.route(failing, lambda route: route.fulfill(status=503, body="down"))
        self.page.goto(project_url(project, "/videos#admin"))
        expect(self.page.locator("[data-slot=alert]")).to_contain_text("Error: HTTP 503: Service Unavailable")
        self.page.unroute(failing)
        self.page.get_by_role("button", name="Retry", exact=True).click()
        expect(self.cards()).to_have_count(24)


class RoleTest(BrowserTestCase):
    def test_admin_mode_shows_all_tabs_section_switch_and_remembered_sort(self):
        project = new_project("admin")
        ids = seed_many_cards(project, 3)
        self.page.goto(project_url(project, "/videos#admin"))
        tabs = self.page.get_by_role("navigation", name="Views").get_by_role("tab")
        expect(tabs).to_have_text(["All", "Needs Designer", "Designer Video", "Pending", "Trash"])
        expect(self.page.get_by_role("tab", name="Video", exact=True)).to_have_attribute("aria-selected", "true")

        sort = self.page.get_by_title("Toggle sort order")
        expect(sort).to_have_text("Oldest")
        self.assertEqual(self.cards().evaluate_all("els => els.map(e => e.dataset.id)"), ids)
        sort.click()
        expect(sort).to_have_text("Newest")
        expect(self.cards().first).to_have_attribute("data-id", ids[-1])
        self.assertEqual(self.page.evaluate("localStorage.getItem('mediaManagerSort')"), "desc")

        self.page.reload()
        expect(self.page.get_by_title("Toggle sort order")).to_have_text("Newest")
        expect(self.cards().first).to_have_attribute("data-id", ids[-1])

        self.page.get_by_role("tab", name="Audio", exact=True).click()
        expect(self.page).to_have_url(re.compile(r"/audio/todo#admin$"))
        expect(tabs).to_have_text(["TODO", "Approved", "Trash"])
        expect(self.page.get_by_role("heading", level=1)).to_have_text("TODO (0)")

    def test_admin_direct_view_url_keeps_the_url_on_tab_click(self):
        project, _ = seed_views_project()
        self.page.goto(project_url(project, "/videos/needs-designer#admin"))
        expect(self.page.get_by_role("heading", level=1)).to_have_text("Needs Designer (2)")
        self.page.get_by_role("tab", name="Pending", exact=True).click()
        expect(self.page.get_by_role("heading", level=1)).to_have_text("Pending (1)")
        expect(self.page).to_have_url(re.compile(r"/videos/needs-designer#admin$"))

    def test_non_admin_designer_queue_has_no_navigation(self):
        project, cards = seed_views_project()
        self.page.goto(project_url(project, "/videos"))
        self.page.evaluate("localStorage.setItem('mediaManagerSort', 'desc')")
        for path, label, expected in [
            ("/videos/needs-designer", "Needs Designer", ["plain", "pending"]),
            ("/videos", "All", ["plain", "linked", "pending"]),
        ]:
            with self.subTest(path=path):
                self.page.goto(project_url(project, path))
                expect(self.page.get_by_role("heading", level=1)).to_have_text(f"{label} ({len(expected)})")
                expect(self.page.get_by_role("tab")).to_have_count(0)
                expect(self.page.get_by_role("navigation")).to_have_count(0)
                expect(self.page.get_by_title("Toggle sort order")).to_have_count(0)
                # Non-admin sort is always oldest first.
                ids = self.cards().evaluate_all("els => els.map(e => e.dataset.id)")
                self.assertEqual(ids, [cards[key] for key in expected])

    def test_non_admin_audio_has_todo_and_approved_tabs_only(self):
        project = new_project("audio")
        self.page.goto(project_url(project, "/audio"))
        tabs = self.page.get_by_role("navigation", name="Views").get_by_role("tab")
        expect(tabs).to_have_text(["TODO", "Approved"])
        expect(self.page.get_by_role("tab", name="Video", exact=True)).to_have_count(0)
        expect(self.page.get_by_text("No audio files in this view")).to_be_visible()
