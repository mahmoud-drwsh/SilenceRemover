"""Browser tests for audio review, trash, restore, and permanent delete (#59)."""

import time

from playwright.sync_api import Route, expect

from base import (
    BrowserTestCase,
    api,
    file_row,
    new_project,
    project_url,
    seed_audio,
    seed_card,
    upload_audio,
)

FILES_URL = "**/api/files/*?type=*"


class ReviewTestCase(BrowserTestCase):
    def card(self, file_id: str):
        return self.page.locator(f"[data-slot=card][data-id='{file_id}']")

    def status(self, file_id: str):
        return self.card(file_id).get_by_role("status")

    def title_field(self, file_id: str):
        return self.card(file_id).get_by_role("textbox")

    def confirm(self, button: str):
        dialog = self.page.get_by_role("alertdialog")
        expect(dialog).to_be_visible()
        dialog.get_by_role("button", name=button, exact=True).click()
        expect(dialog).to_have_count(0)

    def heading(self):
        return self.page.get_by_role("heading", level=1)


class AutosaveTest(ReviewTestCase):
    def test_autosave_shows_each_save_state(self):
        project = new_project("review")
        audio = seed_audio(project, "clip-autosave", "Old title")
        held: list[Route] = []
        bodies: list[dict] = []

        def hold(route: Route) -> None:
            bodies.append(route.request.post_data_json)
            held.append(route)

        self.page.route(FILES_URL, hold)
        self.page.goto(project_url(project, "/audio"))
        field = self.title_field(audio)
        expect(field).to_have_value("Old title")
        expect(field).to_have_attribute("dir", "auto")

        field.fill("عنوان جديد")
        expect(self.status(audio)).to_have_text("Typing...")
        # The save starts 1000 ms after the last input. The request is held.
        expect(self.status(audio)).to_have_text("Saving...", timeout=5000)
        self.assertEqual(len(held), 1)
        self.assertEqual(bodies[0], {"tags": ["todo"], "title": "عنوان جديد"})
        held[0].continue_()
        expect(self.status(audio)).to_have_text("✓ Saved")
        self.assertEqual(file_row(project, audio, "audio")["title"], "عنوان جديد")
        # "Saved" goes away after 3000 ms.
        expect(self.status(audio)).to_have_text("", timeout=6000)

        self.page.unroute(FILES_URL)
        self.page.route(FILES_URL, lambda route: route.fulfill(status=500, body="storage down"))
        field.fill("Another title")
        expect(self.status(audio)).to_have_text("✗ Error: storage down", timeout=5000)
        self.assertEqual(file_row(project, audio, "audio")["title"], "عنوان جديد")

    def test_autosave_waits_until_typing_stops(self):
        project = new_project("review")
        audio = seed_audio(project, "clip-debounce", "")
        puts: list[str] = []
        self.page.on("request", lambda r: puts.append(r.url) if r.method == "PUT" else None)
        self.page.goto(project_url(project, "/audio"))
        field = self.title_field(audio)
        field.press_sequentially("abc", delay=300)
        expect(self.status(audio)).to_have_text("✓ Saved", timeout=5000)
        self.assertEqual(len(puts), 1)
        self.assertEqual(file_row(project, audio, "audio")["title"], "abc")

    def test_waiting_autosave_is_sent_when_the_card_unmounts(self):
        project = new_project("review")
        audio = seed_audio(project, "clip-unmount", "Old title")
        self.page.goto(project_url(project, "/audio"))
        self.title_field(audio).fill("Typed before tab change")
        expect(self.status(audio)).to_have_text("Typing...")
        # A tab change before the 1000 ms autosave timer ends unmounts the
        # card. The card sends the waiting save and does not drop it.
        self.page.get_by_role("tab", name="Approved").click()
        expect(self.heading()).to_have_text("Approved (0)")
        deadline = time.monotonic() + 5
        while file_row(project, audio, "audio")["title"] != "Typed before tab change":
            self.assertLess(time.monotonic(), deadline, "the waiting autosave was not sent")
            time.sleep(0.1)

    def test_approval_waits_for_the_running_autosave(self):
        project = new_project("review")
        audio = seed_audio(project, "clip-order", "Old title")
        held: list[Route] = []
        bodies: list[dict] = []

        def hold_first(route: Route) -> None:
            bodies.append(route.request.post_data_json)
            if len(bodies) == 1:
                held.append(route)
            else:
                route.continue_()

        self.page.route(FILES_URL, hold_first)
        self.page.goto(project_url(project, "/audio"))
        self.title_field(audio).fill("Draft title")
        expect(self.status(audio)).to_have_text("Saving...", timeout=5000)
        self.card(audio).get_by_role("button", name="Approve title").click()
        # The approval PUT waits until the autosave PUT ends.
        self.page.wait_for_timeout(500)
        self.assertEqual(len(bodies), 1)
        held[0].continue_()
        expect(self.heading()).to_have_text("TODO (0)")
        self.assertEqual(bodies, [
            {"tags": ["todo"], "title": "Draft title"},
            {"tags": ["ready"], "title": "Draft title"},
        ])
        row = file_row(project, audio, "audio")
        self.assertEqual((row["tags"], row["review_status"], row["title"]), (["ready"], "approved", "Draft title"))

    def test_autosave_in_trash_keeps_the_trash_tag(self):
        project = new_project("review")
        audio = seed_audio(project, "clip-trash-edit", "x", tags=["trash"], visibility="trash")
        self.page.goto(project_url(project, "/audio/trash#admin"))
        self.title_field(audio).fill("Trash title")
        expect(self.status(audio)).to_have_text("✓ Saved", timeout=5000)
        row = file_row(project, audio, "audio")
        self.assertEqual((row["tags"], row["visibility"], row["title"]), (["trash"], "trash", "Trash title"))


class ReviewActionsTest(ReviewTestCase):
    def test_approve_moves_audio_to_approved_with_read_only_title(self):
        project = new_project("review")
        audio = seed_audio(project, "clip-approve", "First title")
        self.page.goto(project_url(project, "/audio"))
        self.title_field(audio).fill("  Final title  ")
        self.card(audio).get_by_role("button", name="Approve title").click()
        expect(self.heading()).to_have_text("TODO (0)")
        row = file_row(project, audio, "audio")
        self.assertEqual((row["tags"], row["review_status"], row["title"]), (["ready"], "approved", "Final title"))

        self.page.get_by_role("tab", name="Approved").click()
        expect(self.heading()).to_have_text("Approved (1)")
        card = self.card(audio)
        expect(card.get_by_text("Approved", exact=True)).to_be_visible()
        expect(self.title_field(audio)).to_have_value("Final title")
        expect(self.title_field(audio)).not_to_be_editable()
        expect(card.get_by_role("button", name="Approve title")).to_have_count(0)
        expect(card.get_by_role("button", name="Discard audio")).to_have_count(0)

    def test_empty_title_blocks_approval(self):
        project = new_project("review")
        audio = seed_audio(project, "clip-empty", None)
        puts: list[str] = []
        self.page.on("request", lambda r: puts.append(r.url) if r.method == "PUT" else None)
        self.page.goto(project_url(project, "/audio"))
        expect(self.title_field(audio)).to_have_value("")
        self.card(audio).get_by_role("button", name="Approve title").click()
        expect(self.status(audio)).to_have_text("Enter a title before approval.")
        time.sleep(1.5)
        self.assertEqual(puts, [])
        row = file_row(project, audio, "audio")
        self.assertEqual((row["tags"], row["review_status"]), (["todo"], "todo"))
        expect(self.card(audio)).to_be_visible()

    def test_reopen_moves_audio_back_to_todo(self):
        project = new_project("review")
        audio = seed_audio(project, "clip-reopen", "Done title", tags=["ready"], review_status="approved")
        self.page.goto(project_url(project, "/audio/approved"))
        self.card(audio).get_by_role("button", name="Reopen review").click()
        expect(self.heading()).to_have_text("Approved (0)")
        row = file_row(project, audio, "audio")
        self.assertEqual((row["tags"], row["review_status"], row["title"]), (["todo"], "todo", "Done title"))
        self.page.get_by_role("tab", name="TODO").click()
        expect(self.title_field(audio)).to_be_editable()

    def test_discard_after_confirmation_also_for_non_admin(self):
        project = new_project("review")
        audio = seed_audio(project, "clip-discard", "Not useful")
        self.page.goto(project_url(project, "/audio"))
        self.card(audio).get_by_role("button", name="Discard audio").click()
        dialog = self.page.get_by_role("alertdialog")
        expect(dialog.get_by_role("heading")).to_have_text("Discard audio?")
        expect(dialog).to_contain_text("This audio clip is not useful for title review and will be moved to trash.")
        dialog.get_by_role("button", name="Cancel").click()
        expect(dialog).to_have_count(0)
        self.assertEqual(file_row(project, audio, "audio")["tags"], ["todo"])

        self.card(audio).get_by_role("button", name="Discard audio").click()
        self.confirm("Discard")
        expect(self.heading()).to_have_text("TODO (0)")
        row = file_row(project, audio, "audio")
        self.assertEqual((row["tags"], row["visibility"]), (["trash"], "trash"))

    def test_action_error_is_shown(self):
        project = new_project("review")
        audio = seed_audio(project, "clip-error", "Title")
        self.page.goto(project_url(project, "/audio"))
        self.page.route(FILES_URL, lambda route: route.fulfill(status=500, body='{"detail":"Internal server error"}'))
        self.card(audio).get_by_role("button", name="Approve title").click()
        expect(self.status(audio)).to_have_text('✗ Error: {"detail":"Internal server error"}')
        self.assertEqual(file_row(project, audio, "audio")["review_status"], "todo")


class BulkApproveTest(ReviewTestCase):
    def test_bulk_approval_after_confirmation_shows_the_count(self):
        project = new_project("bulk")
        seed_audio(project, "bulk-1", "One")
        seed_audio(project, "bulk-2", None)
        seed_audio(project, "bulk-trash", "T", tags=["trash"], visibility="trash")
        seed_audio(project, "bulk-done", "D", tags=["ready"], review_status="approved")
        self.page.goto(project_url(project, "/audio#admin"))
        expect(self.heading()).to_have_text("TODO (2)")

        self.page.get_by_role("button", name="Approve pending audio").click()
        dialog = self.page.get_by_role("alertdialog")
        expect(dialog.get_by_role("heading")).to_have_text("Approve all pending audio?")
        expect(dialog).to_contain_text("This does not affect trashed audio.")
        dialog.get_by_role("button", name="Cancel").click()
        self.assertEqual(file_row(project, "bulk-1", "audio")["review_status"], "todo")

        self.page.get_by_role("button", name="Approve pending audio").click()
        self.confirm("Approve all")
        expect(self.page.locator("[data-bulk-result]")).to_have_text("Approved 2 audio item(s).")
        expect(self.heading()).to_have_text("TODO (0)")
        for audio_id in ("bulk-1", "bulk-2"):
            row = file_row(project, audio_id, "audio")
            self.assertEqual((row["tags"], row["review_status"]), (["ready"], "approved"))
        self.assertEqual(file_row(project, "bulk-trash", "audio")["tags"], ["trash"])

    def test_bulk_approval_only_on_admin_todo_tab(self):
        project = new_project("bulk")
        self.page.goto(project_url(project, "/audio/approved#admin"))
        expect(self.heading()).to_have_text("Approved (0)")
        expect(self.page.get_by_role("button", name="Approve pending audio")).to_have_count(0)
        self.page.get_by_role("tab", name="TODO").click()
        expect(self.page.get_by_role("button", name="Approve pending audio")).to_be_visible()


class TrashTest(ReviewTestCase):
    def test_video_trash_restore_and_permanent_delete(self):
        project = new_project("trash")
        card = seed_card(project, "v-trash-no-overlay", "Trash me")
        self.page.goto(project_url(project, "/videos#admin"))
        expect(self.heading()).to_have_text("All (1)")
        self.card(card).get_by_role("button", name="Move to Trash").click()
        dialog = self.page.get_by_role("alertdialog")
        expect(dialog).to_contain_text("This file will be moved to trash. You can restore it later.")
        self.confirm("Move to Trash")
        expect(self.heading()).to_have_text("All (0)")
        row = file_row(project, card, "video")
        self.assertEqual((row["tags"], row["visibility"]), (["trash"], "trash"))

        self.page.get_by_role("tab", name="Trash").click()
        expect(self.heading()).to_have_text("Trash (1)")
        self.card(card).get_by_role("button", name="Restore to All").click()
        expect(self.page.get_by_role("alertdialog")).to_contain_text('"Trash me" will be restored.')
        self.confirm("Restore")
        expect(self.heading()).to_have_text("Trash (0)")
        row = file_row(project, card, "video")
        self.assertEqual((row["tags"], row["visibility"]), ([], "active"))

        status, _, _ = api(project, f"/files/{card}?type=video", "PUT", {"tags": ["trash"]})
        self.assertEqual(status, 200)
        self.page.reload()
        expect(self.heading()).to_have_text("Trash (1)")
        self.card(card).get_by_role("button", name="Delete Permanently").click()
        expect(self.page.get_by_role("alertdialog")).to_contain_text(
            '"Trash me" will be permanently deleted. This cannot be undone.')
        self.page.get_by_role("alertdialog").get_by_role("button", name="Cancel").click()
        self.assertIsNotNone(file_row(project, card, "video"))
        self.card(card).get_by_role("button", name="Delete Permanently").click()
        self.confirm("Delete Permanently")
        expect(self.heading()).to_have_text("Trash (0)")
        self.assertIsNone(file_row(project, card, "video"))

    def test_audio_restore_to_todo_and_permanent_delete(self):
        project = new_project("trash")
        keep = upload_audio(project, "a-restore", "Restore me")
        api(project, f"/files/{keep}?type=audio", "PUT", {"tags": ["trash"]})
        gone = seed_audio(project, "a-delete", "Delete me", tags=["trash"], visibility="trash")
        self.page.goto(project_url(project, "/audio/trash#admin"))
        expect(self.heading()).to_have_text("Trash (2)")
        expect(self.card(keep).get_by_role("button", name="Approve title")).to_have_count(0)

        self.card(keep).get_by_role("button", name="Restore to TODO").click()
        self.confirm("Restore")
        expect(self.heading()).to_have_text("Trash (1)")
        row = file_row(project, keep, "audio")
        self.assertEqual((row["tags"], row["visibility"], row["review_status"]), (["todo"], "active", "todo"))

        self.card(gone).get_by_role("button", name="Delete Permanently").click()
        self.confirm("Delete Permanently")
        expect(self.heading()).to_have_text("Trash (0)")
        self.assertIsNone(file_row(project, gone, "audio"))

        self.page.get_by_role("tab", name="TODO").click()
        expect(self.card(keep)).to_be_visible()

    def test_delete_error_is_shown(self):
        project = new_project("trash")
        card = seed_card(project, "v-err-no-overlay", "Err", visibility="trash", tags=["trash"])
        self.page.goto(project_url(project, "/videos/trash#admin"))
        self.page.route(FILES_URL, lambda route: route.fulfill(status=500, body="delete failed"))
        self.card(card).get_by_role("button", name="Delete Permanently").click()
        self.confirm("Delete Permanently")
        expect(self.card(card).locator("[data-slot=alert]")).to_have_text("Error: delete failed")
        self.assertIsNotNone(file_row(project, card, "video"))


class NonAdminTest(ReviewTestCase):
    def test_non_admin_does_not_see_admin_actions(self):
        project = new_project("roles")
        audio = seed_audio(project, "r-audio", "Audio")
        seed_audio(project, "r-audio-trash", "Trashed", tags=["trash"], visibility="trash")
        card = seed_card(project, "r-card-no-overlay", "Card")
        trashed = seed_card(project, "r-trashed-no-overlay", "Trashed card", visibility="trash", tags=["trash"])

        self.page.goto(project_url(project, "/audio"))
        expect(self.heading()).to_have_text("TODO (1)")
        expect(self.page.get_by_role("tab", name="Trash")).to_have_count(0)
        expect(self.page.get_by_role("button", name="Approve pending audio")).to_have_count(0)
        # Review actions stay for a non-admin.
        expect(self.card(audio).get_by_role("button", name="Approve title")).to_be_visible()
        expect(self.card(audio).get_by_role("button", name="Discard audio")).to_be_visible()

        self.page.goto(project_url(project, "/audio/trash"))
        expect(self.cards()).to_have_count(1)
        expect(self.page.get_by_role("button", name="Restore to TODO")).to_have_count(0)
        expect(self.page.get_by_role("button", name="Delete Permanently")).to_have_count(0)

        self.page.goto(project_url(project, "/videos"))
        expect(self.card(card)).to_be_visible()
        expect(self.page.get_by_role("button", name="Move to Trash")).to_have_count(0)

        self.page.goto(project_url(project, "/videos/trash"))
        expect(self.card(trashed)).to_be_visible()
        expect(self.page.get_by_role("button", name="Restore to All")).to_have_count(0)
        expect(self.page.get_by_role("button", name="Delete Permanently")).to_have_count(0)


class PlayTest(ReviewTestCase):
    """Needs the stream route (#58)."""

    def test_inline_play_with_one_item_at_a_time(self):
        project = new_project("play")
        first = upload_audio(project, "p-first", "First")
        second = upload_audio(project, "p-second", "Second")
        self.page.goto(project_url(project, "/audio"))
        expect(self.cards()).to_have_count(2)
        player_one = self.card(first).locator("audio")
        player_two = self.card(second).locator("audio")
        expect(player_one.locator("source")).to_have_attribute(
            "src", f"/projects/test-token/{project}/stream/{first}?type=audio")
        expect(player_one).to_have_attribute("aria-label", "Preview First")

        # A click gives the page user activation, so play() is allowed.
        self.page.mouse.click(2, 2)
        player_one.evaluate("el => el.play()")
        self.page.wait_for_function(
            "el => !el.paused && el.currentTime > 0", arg=player_one.element_handle())
        player_two.evaluate("el => el.play()")
        self.page.wait_for_function(
            "el => !el.paused && el.currentTime > 0", arg=player_two.element_handle())
        self.assertTrue(player_one.evaluate("el => el.paused"))
        self.assertGreater(player_two.evaluate("el => el.duration"), 2.5)
