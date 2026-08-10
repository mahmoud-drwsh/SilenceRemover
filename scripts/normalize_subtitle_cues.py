#!/usr/bin/env python3
"""Deterministically normalize production SRT cues and enqueue safe remux jobs."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages")]

from sr_media_manager import MediaManagerClient  # noqa: E402
from scripts.backfill_served_subtitles import api, download  # noqa: E402

TARGET_CUE_SECONDS = 8.0
MAX_CUE_SECONDS = 10.0
MAX_MOV_TEXT_BYTES = 1_800
TIMING_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})$"
)


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def _timestamp(seconds: float) -> str:
    millis = max(0, round(seconds * 1_000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1_000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _seconds(parts: tuple[str, ...]) -> float:
    hours, minutes, seconds, millis = map(int, parts)
    if minutes >= 60 or seconds >= 60:
        raise ValueError("Invalid SRT timestamp")
    return hours * 3_600 + minutes * 60 + seconds + millis / 1_000


def parse_srt(raw: str) -> list[Cue]:
    blocks = [block for block in re.split(r"\r?\n\s*\r?\n", raw.strip()) if block.strip()]
    cues: list[Cue] = []
    previous_end = 0.0
    for expected, block in enumerate(blocks, start=1):
        lines = block.splitlines()
        if len(lines) < 3 or lines[0].strip() != str(expected):
            raise ValueError("SRT cues must be sequential and contain text")
        match = TIMING_RE.fullmatch(lines[1].strip())
        if not match:
            raise ValueError("Invalid SRT timing line")
        start, end = _seconds(match.groups()[:4]), _seconds(match.groups()[4:])
        text = " ".join(" ".join(lines[2:]).split())
        if not text or start < previous_end or end <= start:
            raise ValueError("SRT cues must be non-empty, positive, and non-overlapping")
        cues.append(Cue(start, end, text))
        previous_end = end
    if not cues:
        raise ValueError("SRT contains no cues")
    return cues


def render_srt(cues: list[Cue]) -> str:
    lines: list[str] = []
    for index, cue in enumerate(cues, start=1):
        lines.extend([
            str(index),
            f"{_timestamp(cue.start)} --> {_timestamp(cue.end)}",
            cue.text,
            "",
        ])
    return "\n".join(lines) + "\n"


def _balanced_groups(words: list[str], count: int) -> list[list[str]]:
    count = max(1, min(count, len(words)))
    base, extra = divmod(len(words), count)
    groups: list[list[str]] = []
    cursor = 0
    for index in range(count):
        size = base + (1 if index < extra else 0)
        groups.append(words[cursor:cursor + size])
        cursor += size
    return groups


def split_cue(cue: Cue) -> list[Cue]:
    duration = cue.end - cue.start
    payload_bytes = len(cue.text.encode("utf-8"))
    if duration <= MAX_CUE_SECONDS and payload_bytes <= MAX_MOV_TEXT_BYTES:
        return [cue]
    words = cue.text.split()
    count = max(
        math.ceil(duration / TARGET_CUE_SECONDS),
        math.ceil(payload_bytes / MAX_MOV_TEXT_BYTES),
    )
    groups = _balanced_groups(words, count)
    total_words = len(words)
    consumed = 0
    result: list[Cue] = []
    for index, group in enumerate(groups):
        start = cue.start + duration * (consumed / total_words)
        consumed += len(group)
        end = cue.end if index == len(groups) - 1 else cue.start + duration * (consumed / total_words)
        result.append(Cue(start, end, " ".join(group)))
    return result


def normalize_srt(raw: str) -> str:
    normalized = [part for cue in parse_srt(raw) for part in split_cue(cue)]
    rendered = render_srt(normalized)
    reparsed = parse_srt(rendered)
    if any(cue.end - cue.start > MAX_CUE_SECONDS + 0.001 for cue in reparsed):
        raise ValueError("Normalized cue exceeds maximum duration")
    if any(len(cue.text.encode("utf-8")) > MAX_MOV_TEXT_BYTES for cue in reparsed):
        raise ValueError("Normalized cue exceeds mov_text payload limit")
    return rendered


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-manager-url", required=True)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "temp" / "subtitle_normalization")
    parser.add_argument("--id", action="append", dest="ids")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--enqueue", action="store_true")
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    client = MediaManagerClient(args.media_manager_url)
    items = client.get_subtitle_files()
    client._client.close()
    if args.ids:
        wanted = set(args.ids)
        items = [item for item in items if item["id"] in wanted or item.get("source_id") in wanted]
    items.sort(key=lambda item: item["id"])
    if args.limit is not None:
        items = items[:args.limit]

    def process(index: int, item: dict) -> tuple[str, str, str | None]:
        worker = MediaManagerClient(args.media_manager_url)
        source_id = item.get("source_id") or item["id"].removesuffix("-subtitles")
        source = args.work_dir / f"{item['id']}.input.srt"
        output = args.work_dir / f"{item['id']}.srt"
        try:
            download(worker, item["id"], "subtitle", source)
            raw = source.read_text(encoding="utf-8")
            normalized = normalize_srt(raw)
            output.write_text(normalized, encoding="utf-8", newline="\n")
            if normalized == raw.replace("\r\n", "\n"):
                return item["id"], "unchanged", None
            if not args.dry_run:
                worker.upload_subtitle(source_id, item.get("title") or source_id, output)
            print(f"[NORMALIZE {index}/{len(items)}] {item['id']}", flush=True)
            return item["id"], "changed", None
        except Exception as error:
            return item["id"], "failed", str(error)
        finally:
            worker._client.close()

    counts = {"changed": 0, "unchanged": 0, "failed": 0}
    errors: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = [pool.submit(process, index, item) for index, item in enumerate(items, start=1)]
        for future in as_completed(futures):
            item_id, state, error = future.result()
            counts[state] += 1
            if error:
                errors.append({"id": item_id, "error": error})
    if args.enqueue and not args.dry_run and not errors:
        enqueue_client = MediaManagerClient(args.media_manager_url)
        api(enqueue_client, "POST", "/api/remux/enqueue", {})
        enqueue_client._client.close()
    report = {**counts, "errors": errors, "dry_run": args.dry_run, "output_sha256": {
        path.name: sha256(path) for path in sorted(args.work_dir.glob("*.srt")) if not path.name.endswith(".input.srt")
    }}
    (args.work_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("changed", "unchanged", "failed", "dry_run")}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
