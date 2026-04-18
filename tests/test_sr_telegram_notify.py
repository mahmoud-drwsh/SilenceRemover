"""Tests for optional Telegram text notifications."""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

from sr_telegram_notify import api as telegram_api
from sr_telegram_notify import notify_final_encoding_started, notify_final_output_ready


class TestTelegramNotify(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    @patch.object(telegram_api, "send_message_text")
    def test_noop_when_unconfigured(self, send_mock: MagicMock) -> None:
        notify_final_output_ready(
            video_index=2,
            total_videos=5,
            input_name="clip.mp4",
            title="Hello",
        )
        notify_final_encoding_started(
            video_index=2,
            total_videos=5,
            input_name="clip.mp4",
            title="Hello",
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
            video_index=2,
            total_videos=5,
            input_name="clip.mp4",
            title="My Title",
        )
        send_mock.assert_called_once()
        kwargs = send_mock.call_args.kwargs
        self.assertEqual(kwargs["token"], "secret")
        self.assertEqual(kwargs["chat_id"], "99")
        text = kwargs["text"]
        self.assertIn("✅", text)  # Emoji indicator
        self.assertIn("2/5", text)  # Video counter
        self.assertIn("clip", text)  # Basename (no extension)
        self.assertIn("My Title", text)  # Title (no extension)
        self.assertIn(":", text)  # Colon separators

    @patch.dict(
        "os.environ",
        {"TELEGRAM_BOT_TOKEN": "secret", "TELEGRAM_CHAT_ID": "99"},
        clear=True,
    )
    @patch.object(telegram_api, "send_message_text")
    def test_started_message_includes_progress(self, send_mock: MagicMock) -> None:
        notify_final_encoding_started(
            video_index=1,
            total_videos=3,
            input_name="a.mp4",
            title="T",
        )
        send_mock.assert_called_once()
        text = send_mock.call_args.kwargs["text"]
        self.assertIn("▶️", text)  # Emoji indicator
        self.assertIn("1/3", text)  # Video counter
        self.assertIn("a", text)  # Basename (no extension)
        self.assertIn("T", text)  # Title (no extension)

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
                video_index=1,
                total_videos=1,
                input_name="a.mp4",
                title="t",
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
                video_index=1,
                total_videos=1,
                input_name="a.mp4",
                title="t",
            )
        send_mock.assert_not_called()
        self.assertIn("TELEGRAM_BOT_TOKEN", err.getvalue())
