#!/usr/bin/env python3
"""Opt-in, self-cleaning black-box check for server-owned source processing.

The lifecycle is intentionally expressed as injectable boundaries so the normal
test suite can exercise it with fakes.  ``main`` is the only production wiring;
the script is not invoked by CI or deployment code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
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
CLEANUP_ATTEMPTS = 5
CLEANUP_RETRY_DELAY_SECONDS = 1


def redact_text(value: object) -> str:
    """Remove credentials and presigned URLs from a diagnostic message."""
    message = str(value)
    message = re.sub(r"https?://[^\s'\"]+", "<redacted-url>", message, flags=re.IGNORECASE)
    message = re.sub(
        r"((?:authorization\s*:\s*bearer|(?:access[_-]?token|token|api[_-]?key)\s*[=:])\s*)[^\s,;]+",
        r"\1<redacted-credential>",
        message,
        flags=re.IGNORECASE,
    )
    return message


def _operation_result(action: str, file_id: str, file_type: str, result: object) -> None:
    """Reject client helpers that report an unsuccessful HTTP operation."""
    if result is not True:
        raise RuntimeError(
            f"{action} returned an unsuccessful result for {file_type}:{file_id}: {result!r}"
        )


def _cleanup_failure(action: str, file_id: str, file_type: str, error: BaseException) -> str:
    return redact_text(f"{action} failed for {file_type}:{file_id}: {type(error).__name__}: {error}")


def _artifact_absent(client: Any, file_id: str, file_type: str) -> bool:
    if hasattr(client, "verify_absent"):
        return client.verify_absent(file_id, file_type) is True
    response = client._client.get(client._url(f"/api/files?type={file_type}&check_id={file_id}"))
    response.raise_for_status()
    rows = response.json()
    return not any(row.get("exists") for row in rows)


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


def check_health(client: Any) -> None:
    response = client._client.get(f"{client.base_url}/healthz")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError("Media Manager health check did not return ok")


def serve_file(client: Any, file_id: str, file_type: str) -> None:
    response = client._client.get(client._url(f"/stream/{file_id}?type={file_type}"))
    response.raise_for_status()
    if not response.content:
        raise RuntimeError(f"{file_type} {file_id} served an empty body")


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def cleanup_artifacts(
    client: Any,
    source_id: str,
    *,
    wait: Callable[..., Any] | None = None,
    attempts: int = CLEANUP_ATTEMPTS,
    retry_delay_seconds: float = CLEANUP_RETRY_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    """Trash/delete every artifact, retrying until readback proves no leftovers."""
    if attempts < 1:
        raise ValueError("cleanup attempts must be positive")
    artifacts = [
        (source_id, "video"),
        (f"{source_id}-no-overlay", "video"),
        (f"{source_id}-subtitles", "subtitle"),
        (source_id, "audio"),
        (source_id, "original"),
    ]
    failures: list[str] = []
    pending: set[tuple[str, str]] = set(artifacts)
    for attempt in range(1, attempts + 1):
        attempt_failures: list[str] = []
        failed_items: set[tuple[str, str]] = set()
        for file_id, file_type in artifacts:
            try:
                # Always perform a second bounded readback pass before
                # returning success. This catches a worker that materializes
                # an artifact just after the first delete/readback pair.
                if attempt > 1 and (file_id, file_type) not in pending and _artifact_absent(client, file_id, file_type):
                    continue
                # A wait hook gives in-flight workers a chance to materialize a
                # late artifact. A timeout is expected during a failed job and
                # must not prevent the trash/delete attempt.
                if wait is not None:
                    try:
                        wait(client, file_id, file_type, 1)
                    except Exception:
                        pass
                if hasattr(client, "delete_file"):
                    _operation_result("delete", file_id, file_type, client.delete_file(file_id, file_type))
                else:
                    _operation_result("trash", file_id, file_type, client.update_tags(file_id, ["trash"], file_type))
                    response = client._client.delete(client._url(f"/api/files/{file_id}?type={file_type}"))
                    response.raise_for_status()
                if not _artifact_absent(client, file_id, file_type):
                    raise RuntimeError("readback still reports the artifact exists")
            except Exception as exc:
                attempt_failures.append(_cleanup_failure("cleanup", file_id, file_type, exc))
                failed_items.add((file_id, file_type))
        if not attempt_failures:
            if attempt == attempts:
                return []
            # Keep one stabilization pass even after a clean first pass so a
            # late worker artifact is discovered before the harness exits.
            pending = set()
            sleep(retry_delay_seconds)
            continue
        failures = attempt_failures
        pending = failed_items
        if attempt < attempts:
            sleep(retry_delay_seconds)
    return failures


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
    health: Callable[[Any], None] = check_health,
    serve: Callable[[Any, str, str], None] = serve_file,
    cleanup_attempts: int = CLEANUP_ATTEMPTS,
    cleanup_retry_delay_seconds: float = CLEANUP_RETRY_DELAY_SECONDS,
    cleanup_sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run one complete source-processing lifecycle at an explicit call site."""
    if not confirm_production:
        raise ValueError("--confirm-production is required; this test creates and removes production media")
    work_dir.mkdir(parents=True, exist_ok=True)
    source_id = (source_id_factory or (lambda: f"black-box-{uuid.uuid4().hex[:18]}"))()
    title = f"Black-box production verification {source_id[-6:]}"
    lifecycle_error: Exception | None = None
    cleanup_errors: list[str] = []
    close_error: Exception | None = None
    result: dict[str, Any] | None = None
    try:
        health(client)
        source = select_bounded_original(client.get_original_files())
        if source is None:
            raise RuntimeError("No bounded production original is available")
        original = work_dir / f"{source_id}.mkv"
        clip = work_dir / f"{source_id}-clip.mkv"
        download(client, str(source["id"]), original)
        expected_checksum = source.get("checksum_sha256")
        if expected_checksum and checksum(original) != expected_checksum:
            raise RuntimeError("downloaded original checksum does not match metadata")
        make_clip_fn(original, clip)
        if not clip.is_file() or clip.stat().st_size <= 0:
            raise RuntimeError("FFmpeg did not produce a non-empty test clip")
        client.upload_original(source_id, clip)
        wait(client, source_id, "original", 90)
        redownloaded = work_dir / f"{source_id}-redownload.mkv"
        download(client, source_id, redownloaded)
        if checksum(redownloaded) != checksum(clip):
            raise RuntimeError("uploaded original failed byte/checksum round-trip")
        review = wait(client, source_id, "audio", timeout_seconds)
        tags = review.get("tags") or []
        if "todo" not in tags or not str(review.get("title") or "").strip():
            raise RuntimeError("invalid review checkpoint")
        # Some deployments expose the checkpoint transcript in the file check
        # payload; validate it when present without requiring a private route.
        if "transcript" in review and not str(review.get("transcript") or "").strip():
            raise RuntimeError("review checkpoint has an empty transcript")
        approve_title(client, source_id, title)
        subtitle = wait(client, f"{source_id}-subtitles", "subtitle", timeout_seconds)
        no_overlay = wait(client, f"{source_id}-no-overlay", "video", timeout_seconds)
        overlaid = wait(client, source_id, "video", timeout_seconds)
        for variant in (no_overlay, overlaid):
            if variant.get("title") != title or variant.get("source_id") != source_id:
                raise RuntimeError("approved title or original link did not reach both variants")
            if not isinstance(variant.get("duration"), (int, float)) or variant["duration"] <= 0:
                raise RuntimeError("variant has an invalid duration")
            if abs(variant["duration"] - round(variant["duration"])) <= 0.001:
                raise RuntimeError("variant duration is not fractional")
            serve(client, str(variant["id"]), "video")
        if subtitle.get("source_id") != source_id:
            raise RuntimeError("subtitle is not linked to the original")
        serve(client, f"{source_id}-subtitles", "subtitle")
        duration = overlaid.get("duration")
        if not isinstance(duration, (int, float)) or duration <= 0:
            raise RuntimeError("invalid final duration")
        result = {"ok": True, "source_id": source_id, "duration": duration, "variants": ["no-overlay", "overlaid"]}
    except Exception as exc:
        # Cleanup is deliberately deferred to one common finalization path so
        # close() failures cannot replace the lifecycle failure that matters.
        lifecycle_error = exc
    finally:
        try:
            cleanup_errors = cleanup_artifacts(
                client,
                source_id,
                wait=wait,
                attempts=cleanup_attempts,
                retry_delay_seconds=cleanup_retry_delay_seconds,
                sleep=cleanup_sleep,
            )
        except Exception as exc:
            cleanup_errors = [redact_text(f"cleanup operation failed: {type(exc).__name__}: {exc}")]
        try:
            client.close()
        except Exception as exc:
            close_error = exc

    if lifecycle_error is not None:
        # Keep the original assertion/HTTP/worker error as the raised error;
        # notes preserve cleanup diagnostics without obscuring its traceback.
        if cleanup_errors:
            lifecycle_error.add_note("Cleanup diagnostics: " + "; ".join(cleanup_errors))
        if close_error is not None:
            lifecycle_error.add_note(
                redact_text(f"Client close failed: {type(close_error).__name__}: {close_error}")
            )
        raise lifecycle_error
    if cleanup_errors or close_error is not None:
        diagnostics = list(cleanup_errors)
        if close_error is not None:
            diagnostics.append(redact_text(f"Client close failed: {type(close_error).__name__}: {close_error}"))
        raise RuntimeError("black-box cleanup could not be verified: " + "; ".join(diagnostics))
    assert result is not None
    return result


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
    try:
        result = run_black_box(MediaManagerClient(), args.work_dir, confirm_production=True, timeout_seconds=args.timeout_seconds)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": redact_text(exc)}}, ensure_ascii=False), flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
