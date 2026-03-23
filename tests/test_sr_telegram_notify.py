"""Tests for optional Telegram text notifications."""

from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sr_telegram_notify import api as telegram_api
from sr_telegram_notify import notify_final_encoding_started, notify_final_output_ready


class TestTelegramNotify(unittest.TestCase):
    def setUp(self) -> None:
        telegram_api._half_config_warned = False

    @patch.dict("os.environ", {}, clear=True)
    @patch.object(telegram_api, "send_message_text")
    def test_noop_when_unconfigured(self, send_mock: MagicMock) -> None:
        notify_final_output_ready(
            phase_index=3,
            total_phases=3,
            video_index=2,
            total_videos=5,
            input_name="clip.mp4",
            title="Hello",
            output_mp4=Path("out.mp4"),
        )
        notify_final_encoding_started(
            phase_index=3,
            total_phases=3,
            video_index=2,
            total_videos=5,
            input_name="clip.mp4",
            title="Hello",
            output_mp4=Path("out.mp4"),
        )
        send_mock.assert_not_called()

    @patch.dict(
        "os.environ",
        {"TELEGRAM_BOT_TOKEN": "secret", "TELEGRAM_CHAT_ID": "99"},
        clear=True,
    )
    @patch.object(telegram_api, "send_message_text")
    def test_sends_message_with_progress(self, send_mock: MagicMock) -> None:
        notify_final_output_ready(
            phase_index=3,
            total_phases=3,
            video_index=2,
            total_videos=5,
            input_name="clip.mp4",
            title="My Title",
            output_mp4=Path("/tmp/FinalName.mp4"),
        )
        send_mock.assert_called_once()
        kwargs = send_mock.call_args.kwargs
        self.assertEqual(kwargs["token"], "secret")
        self.assertEqual(kwargs["chat_id"], "99")
        text = kwargs["text"]
        self.assertIn("Encoding complete", text)
        self.assertIn("Phase 3/3", text)
        self.assertIn("Video 2/5", text)
        self.assertIn("clip.mp4", text)
        self.assertIn("Title: My Title", text)
        self.assertIn("Output: FinalName.mp4", text)

    @patch.dict(
        "os.environ",
        {"TELEGRAM_BOT_TOKEN": "secret", "TELEGRAM_CHAT_ID": "99"},
        clear=True,
    )
    @patch.object(telegram_api, "send_message_text")
    def test_started_message_includes_progress(self, send_mock: MagicMock) -> None:
        notify_final_encoding_started(
            phase_index=3,
            total_phases=3,
            video_index=1,
            total_videos=3,
            input_name="a.mp4",
            title="T",
            output_mp4=Path("planned.mp4"),
        )
        send_mock.assert_called_once()
        text = send_mock.call_args.kwargs["text"]
        self.assertIn("Encoding started", text)
        self.assertIn("Phase 3/3", text)
        self.assertIn("Video 1/3", text)

    @patch.dict(
        "os.environ",
        {"TELEGRAM_BOT_TOKEN": "secret", "TELEGRAM_CHAT_ID": "99"},
        clear=True,
    )
    @patch.object(telegram_api, "send_message_text", side_effect=RuntimeError("network"))
    def test_failure_does_not_propagate(self, _send_mock: MagicMock) -> None:
        err = io.StringIO()
        with patch.object(telegram_api.sys, "stderr", err):
            notify_final_output_ready(
                phase_index=3,
                total_phases=3,
                video_index=1,
                total_videos=1,
                input_name="a.mp4",
                title="t",
                output_mp4=Path("o.mp4"),
            )
        self.assertIn("Telegram notification failed", err.getvalue())

    @patch.dict(
        "os.environ",
        {"TELEGRAM_BOT_TOKEN": "only-token", "TELEGRAM_CHAT_ID": ""},
        clear=True,
    )
    @patch.object(telegram_api, "send_message_text")
    def test_half_config_warns_and_skips(self, send_mock: MagicMock) -> None:
        err = io.StringIO()
        with patch.object(telegram_api.sys, "stderr", err):
            notify_final_output_ready(
                phase_index=3,
                total_phases=3,
                video_index=1,
                total_videos=1,
                input_name="a.mp4",
                title="t",
                output_mp4=Path("o.mp4"),
            )
        send_mock.assert_not_called()
        self.assertIn("TELEGRAM_BOT_TOKEN", err.getvalue())
