"""Internal Telegram Bot API HTTP client (sendMessage only)."""

from __future__ import annotations

import httpx

DEFAULT_API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT_SEC = 30.0


def send_message_text(
    *,
    token: str,
    chat_id: str,
    text: str,
    api_base: str | None = None,
) -> None:
    """POST sendMessage; raises on HTTP error or Telegram ok=false."""
    base = (api_base or DEFAULT_API_BASE).rstrip("/")
    url = f"{base}/bot{token}/sendMessage"
    with httpx.Client(timeout=DEFAULT_TIMEOUT_SEC) as client:
        response = client.post(url, json={"chat_id": chat_id, "text": text})
        response.raise_for_status()
        data = response.json()
    if not data.get("ok"):
        desc = data.get("description") or str(data)
        raise RuntimeError(f"Telegram API error: {desc}")
