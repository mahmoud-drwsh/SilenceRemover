#!/usr/bin/env python3
"""Opt-in, self-cleaning black-box check for server-owned source processing.

The lifecycle is intentionally expressed as injectable boundaries so the normal
test suite can exercise it with fakes.  ``main`` is the only production wiring;
this module is not imported by CI or deployment code.
"""
from __future__ import annotations

import argparse
import subprocess
import time
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import httpx
from sr_media_manager import MediaManagerClient

BOUNDED_ORIGINAL_BYTES = 40 * 1024 * 1024
DEFAULT_CLIP_SECONDS = 25


def select_bounded_original(rows: Iterable[dict[str, Any]], limit: int = BOUNDED_ORIGINAL_BYTES) -> dict[str, Any] | None:
    """Return the smallest positively-sized original within the transfer bound."""
    candidates = []
    for row in rows:
        try:
            size = int(row.get("file_size") or 0)
        except (TypeError, ValueError):
            continue
        if 0 < size <= limit and row.get("id"):
            candidates.append((size, row))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def wait_for(client: Any, file_id: str, file_type: str, timeout: float, *, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Poll the public file-check endpoint until a file is materialized."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client._client.get(client._url(f"/api/files?type={file_type}&check_id={file_id}"))
        response.raise_for_status()
        rows = response.json()
        if rows and rows[0].get("exists"):
            return rows[0]
        sleep(min(5, max(0, deadline - time.monotonic())))
    raise TimeoutError(f"Timed out waiting for {file_type}:{file_id}")


def download_original(client: Any, source_id: str, destination: Path) -> None:
    response = client._client.get(client._url(f"/api/originals/{source_id}/download"))
    response.raise_for_status()
    with httpx.stream("GET", response.json()["url"], timeout=600) as stream:
        stream.raise_for_status()
        with destination.open("wb") as output:
            for chunk in stream.iter_bytes():
                output.write(chunk)


def make_clip(original: Path, clip: Path, seconds: int = DEFAULT_CLIP_SECONDS) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(original), "-t", str(seconds), "-map", "0", "-c", "copy", str(clip)],
        check=True,
    )


def approve_title(client: Any, source_id: str, title: str) -> None:
    """Apply the reviewer title and ready checkpoint through the API seam."""
    if hasattr(client, "approve_audio_title"):
        client.approve_audio_title(source_id, title)
        return
    response = client._client.put(
        client._url(f"/api/files/{source_id}?type=audio"),
        json={"title": title, "tags": ["ready"]},
    )
    response.raise_for_status()


def cleanup_artifacts(client: Any, source_id: str, *, wait: Callable[..., Any] | None = None) -> None:
    """Best-effort trash-then-delete of every artifact, independently."""
    artifacts = [
        (source_id, "video"),
        (f"{source_id}-no-overlay", "video"),
        (f"{source_id}-subtitles", "subtitle"),
        (source_id, "audio"),
        (source_id, "original"),
    ]
    for file_id, file_type in artifacts:
        try:
            # A wait hook is useful for the live race where a failed job has not
            # materialized yet; deletion is still attempted when it times out.
            if wait is not None:
                try:
                    wait(client, file_id, file_type, 1)
                except Exception:
                    pass
            if hasattr(client, "delete_file"):
                client.delete_file(file_id, file_type)
            else:
                client.update_tags(file_id, ["trash"], file_type)
                client._client.delete(client._url(f"/api/files/{file_id}?type={file_type}")).raise_for_status()
        except Exception:
            continue


def run_black_box(
    client: Any,
    work_dir: Path,
    *,
    confirm_production: bool,
    timeout_seconds: int = 900,
    source_id_factory: Callable[[], str] | None = None,
    download: Callable[[Any, str, Path], None] = download_original,
    make_clip_fn: Callable[[Path, Path], None] = make_clip,
    wait: Callable[..., dict[str, Any]] = wait_for,
) -> dict[str, Any]:
    """Run one complete source-processing lifecycle at an explicit call site."""
    if not confirm_production:
        raise ValueError("--confirm-production is required; this test creates and removes production media")
    work_dir.mkdir(parents=True, exist_ok=True)
    source_id = (source_id_factory or (lambda: f"black-box-{uuid.uuid4().hex[:18]}"))()
    title = f"Black-box production verification {source_id[-6:]}"
    try:
        source = select_bounded_original(client.get_original_files())
        if source is None:
            raise RuntimeError("No bounded production original is available")
        original = work_dir / f"{source_id}.mkv"
        clip = work_dir / f"{source_id}-clip.mkv"
        download(client, str(source["id"]), original)
        make_clip_fn(original, clip)
        if not clip.is_file() or clip.stat().st_size <= 0:
            raise RuntimeError("FFmpeg did not produce a non-empty test clip")
        client.upload_original(source_id, clip)
        wait(client, source_id, "original", 90)
        review = wait(client, source_id, "audio", timeout_seconds)
        tags = review.get("tags") or []
        if "todo" not in tags or not str(review.get("title") or "").strip():
            raise RuntimeError("invalid review checkpoint")
        approve_title(client, source_id, title)
        subtitle = wait(client, f"{source_id}-subtitles", "subtitle", timeout_seconds)
        no_overlay = wait(client, f"{source_id}-no-overlay", "video", timeout_seconds)
        overlaid = wait(client, source_id, "video", timeout_seconds)
        for variant in (no_overlay, overlaid):
            if variant.get("title") != title or variant.get("source_id") != source_id:
                raise RuntimeError("approved title or original link did not reach both variants")
        if subtitle.get("source_id") != source_id:
            raise RuntimeError("subtitle is not linked to the original")
        duration = overlaid.get("duration")
        if not isinstance(duration, (int, float)) or duration <= 0:
            raise RuntimeError("invalid final duration")
        return {"ok": True, "source_id": source_id, "duration": duration, "variants": ["no-overlay", "overlaid"]}
    finally:
        cleanup_artifacts(client, source_id, wait=wait)
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-production", action="store_true")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()
    if not args.confirm_production:
        parser.error("--confirm-production is required; this test creates and removes production media")
    # run_black_box owns close() so cleanup and client shutdown also happen
    # when a lifecycle assertion raises.
    result = run_black_box(
        MediaManagerClient(), args.work_dir, confirm_production=True,
        timeout_seconds=args.timeout_seconds,
    )
    print(result)


if __name__ == "__main__":
    main()
