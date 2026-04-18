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
    """Build compact progress message: '1/3: basename: title' (no extensions)."""
    basename = Path(input_name).stem
    title_clean = Path(title).stem
    return f"{video_index}/{total_videos}: {basename}: {title_clean}"


def notify_final_encoding_started(
    video_index: int,
    total_videos: int,
    input_name: str,
    title: str,
) -> None:
    """Notify that Phase 6 final encoding is about to start (before FFmpeg)."""
    body = _progress_body(
        video_index=video_index,
        total_videos=total_videos,
        input_name=input_name,
        title=title,
    )
    _telegram_send_if_configured(f"▶️ {body}")


def notify_final_output_ready(
    video_index: int,
    total_videos: int,
    input_name: str,
    title: str,
) -> None:
    """Notify that Phase 6 encoding finished successfully."""
    body = _progress_body(
        video_index=video_index,
        total_videos=total_videos,
        input_name=input_name,
        title=title,
    )
    _telegram_send_if_configured(f"✅ {body}")


def notify_audio_uploaded(
    *,
    video_index: int,
    total_videos: int,
    input_name: str,
    title: str,
) -> None:
    """Notify that audio snippet was uploaded to Media Manager (Phase 4)."""
    body = _progress_body(
        video_index=video_index,
        total_videos=total_videos,
        input_name=input_name,
        title=title,
    )
    _telegram_send_if_configured(f"🎵 Audio uploaded: {body}")


def notify_video_uploaded(
    *,
    video_index: int,
    total_videos: int,
    input_name: str,
    title: str,
) -> None:
    """Notify that final video was uploaded to Media Manager (Phase 8)."""
    body = _progress_body(
        video_index=video_index,
        total_videos=total_videos,
        input_name=input_name,
        title=title,
    )
    _telegram_send_if_configured(f"🎬 Video uploaded: {body}")
