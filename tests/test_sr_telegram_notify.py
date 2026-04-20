"""Tests for optional Telegram text notifications."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

from sr_telegram_notify import api as telegram_api
from sr_telegram_notify import (
    notify_audio_uploaded,
    notify_final_encoding_started,
    notify_final_output_ready,
    notify_video_uploaded,
)


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
    def test_ready_message_uses_single_word_status(self, send_mock: MagicMock) -> None:
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
        self.assertEqual(kwargs["text"], "READY 2/5\nclip: My Title")

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
        self.assertEqual(send_mock.call_args.kwargs["text"], "STARTED 1/3\na: T")

    @patch.dict(
        "os.environ",
        {"TELEGRAM_BOT_TOKEN": "secret", "TELEGRAM_CHAT_ID": "99"},
        clear=True,
    )
    @patch.object(telegram_api, "send_message_text")
    def test_upload_messages_use_single_word_statuses(self, send_mock: MagicMock) -> None:
        notify_audio_uploaded(
            video_index=1,
            total_videos=2,
            input_name="clip.mp4",
            title="Title",
        )
        notify_video_uploaded(
            video_index=2,
            total_videos=2,
            input_name="clip.mp4",
            title="Title",
        )
        self.assertEqual(send_mock.call_count, 2)
        self.assertEqual(send_mock.call_args_list[0].kwargs["text"], "AUDIO 1/2\nclip: Title")
        self.assertEqual(send_mock.call_args_list[1].kwargs["text"], "VIDEO 2/2\nclip: Title")

    @patch.dict(
        "os.environ",
        {"TELEGRAM_BOT_TOKEN": "secret", "TELEGRAM_CHAT_ID": "99"},
        clear=True,
    )
    @patch.object(telegram_api, "send_message_text", side_effect=RuntimeError("network"))
    def test_failure_does_not_propagate(self, _send_mock: MagicMock) -> None:
        notify_final_output_ready(
            video_index=1,
            total_videos=1,
            input_name="a.mp4",
            title="t",
        )

    @patch.dict(
        "os.environ",
        {"TELEGRAM_BOT_TOKEN": "only-token", "TELEGRAM_CHAT_ID": ""},
        clear=True,
    )
    @patch.object(telegram_api, "send_message_text")
    def test_half_config_skips_send(self, send_mock: MagicMock) -> None:
        notify_final_output_ready(
            video_index=1,
            total_videos=1,
            input_name="a.mp4",
            title="t",
        )
        send_mock.assert_not_called()
