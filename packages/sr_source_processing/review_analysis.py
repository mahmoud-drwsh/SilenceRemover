"""Client adapter for Media Manager's canonical worker review-analysis endpoint."""

from __future__ import annotations

from pathlib import Path

import httpx


class ReviewAnalysisError(RuntimeError):
    """The authenticated Media Manager review-analysis contract failed."""


def analyze_review_ogg(
    client: httpx.Client, endpoint: str, worker_token: str, audio: Path,
) -> tuple[str, str]:
    """Submit a transient review OGG and validate Media Manager's text pair."""
    try:
        with audio.open("rb") as stream:
            response = client.post(
                endpoint,
                headers={"X-Source-Processing-Token": worker_token},
                files={"snippet": ("review.ogg", stream, "audio/ogg")},
            )
        response.raise_for_status()
        payload = response.json()
    except (OSError, httpx.HTTPError, ValueError) as exc:
        raise ReviewAnalysisError(f"Internal review analysis failed: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ReviewAnalysisError("Internal review analysis returned an invalid response")
    transcript = str(payload.get("transcript") or "").strip()
    title = str(payload.get("title") or "").strip()
    if not transcript:
        raise ReviewAnalysisError("Internal review analysis returned empty transcript")
    if not title or "\n" in title:
        raise ReviewAnalysisError("Internal review analysis returned invalid title")
    return transcript, title
