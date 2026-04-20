"""Public API: optional text notifications for final encode start and completion."""

from __future__ import annotations
from pathlib import Path

from ._client import send_message_text

_TELEGRAM_MAX_MESSAGE_LEN = 4096

def _env(name: str) -> str:
    import os

    return (os.environ.get(name) or "").strip()


def _telegram_send_if_configured(text: str) -> None:
    """Send ``text`` if token and chat id are set; never raises."""
    token = _env("TELEGRAM_BOT_TOKEN")
    chat_id = _env("TELEGRAM_CHAT_ID")

    if not token and not chat_id:
        return

    if bool(token) != bool(chat_id):
        return

    api_base = _env("TELEGRAM_API_BASE") or None

    if len(text) > _TELEGRAM_MAX_MESSAGE_LEN:
        text = text[: _TELEGRAM_MAX_MESSAGE_LEN - 3] + "..."

    try:
        send_message_text(token=token, chat_id=chat_id, text=text, api_base=api_base)
    except Exception:
        pass


def _progress_body(
    *,
    video_index: int,
    total_videos: int,
    input_name: str,
    title: str,
) -> str:
    """Build compact detail line: 'basename: title' (no extensions)."""
    basename = Path(input_name).stem
    title_clean = Path(title).stem
    return f"{basename}: {title_clean}"


def _status_message(
    status: str,
    *,
    video_index: int,
    total_videos: int,
    input_name: str,
    title: str,
) -> str:
    body = _progress_body(
        video_index=video_index,
        total_videos=total_videos,
        input_name=input_name,
        title=title,
    )
    return f"{status} {video_index}/{total_videos}\n{body}"


def notify_final_encoding_started(
    video_index: int,
    total_videos: int,
    input_name: str,
    title: str,
) -> None:
    """Notify that Phase 7 final encoding is about to start (before FFmpeg)."""
    _telegram_send_if_configured(_status_message(
        "STARTED",
        video_index=video_index,
        total_videos=total_videos,
        input_name=input_name,
        title=title,
    ))


def notify_final_output_ready(
    video_index: int,
    total_videos: int,
    input_name: str,
    title: str,
) -> None:
    """Notify that Phase 7 encoding finished successfully."""
    _telegram_send_if_configured(_status_message(
        "READY",
        video_index=video_index,
        total_videos=total_videos,
        input_name=input_name,
        title=title,
    ))


def notify_audio_uploaded(
    *,
    video_index: int,
    total_videos: int,
    input_name: str,
    title: str,
) -> None:
    """Notify that audio snippet was uploaded to Media Manager (Phase 4)."""
    _telegram_send_if_configured(_status_message(
        "AUDIO",
        video_index=video_index,
        total_videos=total_videos,
        input_name=input_name,
        title=title,
    ))


def notify_video_uploaded(
    *,
    video_index: int,
    total_videos: int,
    input_name: str,
    title: str,
) -> None:
    """Notify that final video was uploaded to Media Manager (Phase 9)."""
    _telegram_send_if_configured(_status_message(
        "VIDEO",
        video_index=video_index,
        total_videos=total_videos,
        input_name=input_name,
        title=title,
    ))
