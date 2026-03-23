"""Public API: optional text notification when a final encode completes."""

from __future__ import annotations

import sys
from pathlib import Path

from ._client import send_message_text

_TELEGRAM_MAX_MESSAGE_LEN = 4096
_half_config_warned = False


def _env(name: str) -> str:
    import os

    return (os.environ.get(name) or "").strip()


def notify_final_output_ready(
    *,
    phase_index: int,
    total_phases: int,
    video_index: int,
    total_videos: int,
    input_name: str,
    title: str,
    output_mp4: Path,
) -> None:
    """Send a text Telegram message if ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` are set.

    Never raises: failures are printed to stderr. Unconfigured env is a silent no-op.
    """
    global _half_config_warned

    token = _env("TELEGRAM_BOT_TOKEN")
    chat_id = _env("TELEGRAM_CHAT_ID")

    if not token and not chat_id:
        return

    if bool(token) != bool(chat_id):
        if not _half_config_warned:
            _half_config_warned = True
            print(
                "Telegram: set both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, or neither.",
                file=sys.stderr,
            )
        return

    api_base = _env("TELEGRAM_API_BASE") or None

    lines = [
        "Encoding complete",
        f"Phase {phase_index}/{total_phases} — Final output",
        f"Video {video_index}/{total_videos} — {input_name}",
        f"Title: {title}",
        f"Output: {output_mp4.name}",
    ]
    text = "\n".join(lines)
    if len(text) > _TELEGRAM_MAX_MESSAGE_LEN:
        text = text[: _TELEGRAM_MAX_MESSAGE_LEN - 3] + "..."

    try:
        send_message_text(token=token, chat_id=chat_id, text=text, api_base=api_base)
    except Exception as exc:
        print(f"Telegram notification failed: {exc}", file=sys.stderr)
