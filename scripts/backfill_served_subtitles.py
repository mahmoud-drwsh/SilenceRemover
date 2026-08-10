#!/usr/bin/env python3
"""Resumable production subtitle generation and checksum-pinned remux worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages")]

from sr_media_manager import MediaManagerClient  # noqa: E402
from sr_subtitles import generate_srt_from_served_video, mux_srt_track  # noqa: E402

TRANSFER_TIMEOUT = httpx.Timeout(connect=30, read=600, write=600, pool=30)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-show_entries", "stream=index,codec_type,codec_name:stream_disposition=default",
        "-of", "json", str(path),
    ], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def download(client: MediaManagerClient, file_id: str, file_type: str, destination: Path) -> None:
    url = client._url(f"/stream/{quote(file_id, safe='')}?type={file_type}")
    with client._client.stream("GET", url, timeout=TRANSFER_TIMEOUT) as response:
        response.raise_for_status()
        with destination.open("wb") as target:
            for chunk in response.iter_bytes(1024 * 1024):
                target.write(chunk)


def canonical_videos(client: MediaManagerClient) -> list[dict]:
    videos = client.get_video_files(include_trash=True, include_pending=True)
    by_source: dict[str, list[dict]] = {}
    for video in videos:
        source_id = video.get("source_id")
        if source_id and "trash" not in (video.get("tags") or []):
            by_source.setdefault(source_id, []).append(video)
    selected = []
    for source_id, variants in by_source.items():
        variants.sort(key=lambda item: (
            item.get("id") != f"{source_id}-no-overlay",
            item.get("id") != source_id,
            bool(item.get("designer_of_id")),
            item.get("id", ""),
        ))
        selected.append(variants[0])
    return sorted(selected, key=lambda item: item["source_id"])


def generate_missing(client: MediaManagerClient, root: Path, api_key: str, limit: int | None) -> tuple[int, int]:
    existing = {item["id"] for item in client.get_subtitle_files()}
    candidates = [v for v in canonical_videos(client) if f"{v['source_id']}-subtitles" not in existing]
    if limit is not None: candidates = candidates[:limit]
    completed = failed = 0
    for index, video in enumerate(candidates, start=1):
        source_id = video["source_id"]
        item_dir = root / source_id
        item_dir.mkdir(parents=True, exist_ok=True)
        video_path = item_dir / "served.mp4"; srt_path = root / "srt" / f"{source_id}.srt"
        try:
            print(f"[SRT {index}/{len(candidates)}] {source_id}", flush=True)
            if not srt_path.exists():
                download(client, video["id"], "video", video_path)
                media_duration = duration(video_path)
                last_error: Exception | None = None
                for attempt in range(3):
                    try:
                        generate_srt_from_served_video(
                            input_file=video_path, output_path=srt_path, work_dir=item_dir,
                            api_key=api_key, duration=media_duration, log_dir=item_dir,
                        )
                        last_error = None; break
                    except Exception as exc:
                        last_error = exc
                        if attempt < 2: time.sleep(2 ** attempt)
                if last_error: raise last_error
            client.upload_subtitle(source_id, video.get("title") or source_id, srt_path)
            completed += 1
        except Exception as exc:
            failed += 1
            print(f"[SRT FAILED] {source_id}: {exc}", file=sys.stderr, flush=True)
        finally:
            for path in (video_path, item_dir / "served-timeline.wav"):
                path.unlink(missing_ok=True)
            try: item_dir.rmdir()
            except OSError: pass
    return completed, failed


def api(client: MediaManagerClient, method: str, endpoint: str, body: dict | None = None) -> dict:
    response = client._client.request(method, client._url(endpoint), json=body, timeout=TRANSFER_TIMEOUT)
    response.raise_for_status()
    return response.json()


def remux_all(client: MediaManagerClient, root: Path, limit: int | None) -> tuple[int, int]:
    videos = client.get_video_files(include_trash=True, include_pending=True)
    missing = [video for video in videos if video.get("source_id") and not video.get("checksum_sha256") and "trash" not in (video.get("tags") or [])]
    for index, video in enumerate(missing, start=1):
        print(f"[CHECKSUM {index}/{len(missing)}] {video['id']}", flush=True)
        api(client, "POST", f"/api/remux/checksum/{quote(video['id'], safe='')}", {})
    api(client, "POST", "/api/remux/enqueue", {})
    completed = failed = 0
    while limit is None or completed + failed < limit:
        claimed = api(client, "POST", "/api/remux/claim", {})["job"]
        if not claimed: break
        job_id = claimed["id"]; lease = claimed["lease_token"]
        item_dir = root / "remux" / job_id; item_dir.mkdir(parents=True, exist_ok=True)
        video_path = item_dir / "video.mp4"; srt_path = item_dir / "subtitle.srt"
        try:
            print(f"[REMUX] {claimed['video_id']}", flush=True)
            download(client, claimed["video_id"], "video", video_path)
            if sha256(video_path) != claimed["input_checksum_sha256"]:
                raise RuntimeError("downloaded video checksum differs from claimed input")
            download(client, claimed["subtitle_id"], "subtitle", srt_path)
            if sha256(srt_path) != claimed["subtitle_checksum_sha256"]:
                raise RuntimeError("downloaded SRT checksum differs from claimed input")
            mux_srt_track(video_path, srt_path)
            info = probe(video_path)
            subtitles = [stream for stream in info["streams"] if stream["codec_type"] == "subtitle"]
            if len(subtitles) != 1 or subtitles[0]["codec_name"] != "mov_text":
                raise RuntimeError("remux verification did not find exactly one mov_text track")
            checksum = sha256(video_path); size = video_path.stat().st_size
            upload = api(client, "POST", f"/api/remux/{job_id}/upload", {
                "lease_token": lease, "size": size, "checksum_sha256": checksum,
            })
            with video_path.open("rb") as handle:
                result = httpx.put(upload["upload_url"], content=handle, headers={"Content-Type": "video/mp4"}, timeout=TRANSFER_TIMEOUT)
                result.raise_for_status()
            api(client, "POST", f"/api/remux/{job_id}/complete", {"lease_token": lease})
            completed += 1
        except Exception as exc:
            failed += 1
            print(f"[REMUX FAILED] {claimed['video_id']}: {exc}", file=sys.stderr, flush=True)
            try: api(client, "POST", f"/api/remux/{job_id}/fail", {"lease_token": lease, "error": str(exc)})
            except Exception: pass
        finally:
            for path in item_dir.glob("*"): path.unlink(missing_ok=True)
            try: item_dir.rmdir()
            except OSError: pass
    return completed, failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-manager-url", default=os.getenv("MEDIA_MANAGER_URL"))
    parser.add_argument("--work-dir", type=Path, default=ROOT / "temp" / "server_subtitle_backfill")
    parser.add_argument("--stage", choices=["subtitles", "remux", "all", "status"], default="all")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if not args.media_manager_url: parser.error("--media-manager-url or MEDIA_MANAGER_URL is required")
    args.work_dir.mkdir(parents=True, exist_ok=True)
    client = MediaManagerClient(args.media_manager_url)
    if args.stage == "status":
        print(json.dumps(api(client, "GET", "/api/remux/status"), indent=2)); return 0
    failures = 0
    if args.stage in {"subtitles", "all"}:
        key = os.getenv("OPENROUTER_API_KEY", "")
        if not key: parser.error("OPENROUTER_API_KEY is required for subtitle generation")
        done, failed = generate_missing(client, args.work_dir, key, args.limit)
        print(f"Subtitle backfill: completed={done} failed={failed}"); failures += failed
        if failed and args.stage == "all": return 1
    if args.stage in {"remux", "all"}:
        done, failed = remux_all(client, args.work_dir, args.limit)
        print(f"Remux backfill: completed={done} failed={failed}"); failures += failed
    return 1 if failures else 0


if __name__ == "__main__": raise SystemExit(main())
