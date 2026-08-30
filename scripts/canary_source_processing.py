#!/usr/bin/env python3
"""Read-only hosted-original canary for server processing modules."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from sr_media_manager import MediaManagerClient
from sr_source_processing.api import SourceProcessingWorker
from sr_source_processing.review_analysis import analyze_review_ogg
from sr_subtitles import generate_srt_from_trim_segments
from sr_trim_plan import build_trim_plan
from src.core.constants import NON_TARGET_MIN_DURATION_SEC, NON_TARGET_NOISE_THRESHOLD_DB, NON_TARGET_PAD_SEC


def analyze_review_audio(client: MediaManagerClient, worker_token: str, audio: Path) -> tuple[str, str]:
    """Use the same worker-authenticated review analysis adapter as server jobs."""
    endpoint = f"{client.base_url}/internal/source-processing/{client.project}/review-analysis"
    return analyze_review_ogg(client._client, endpoint, worker_token, audio)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_id")
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key: parser.error("OPENROUTER_API_KEY is required")
    worker_token = os.environ.get("SOURCE_PROCESSING_WORKER_TOKEN", "")
    if not worker_token: parser.error("SOURCE_PROCESSING_WORKER_TOKEN is required")
    client = MediaManagerClient()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    original = args.work_dir / "original.mkv"
    if not original.exists():
        with client._client.stream("GET", client._url(f"/stream/{args.source_id}?type=original"), timeout=600) as response:
            response.raise_for_status()
            with original.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 1024): handle.write(chunk)
    plan_path = args.work_dir / "trim-plan.json"
    if plan_path.exists():
        plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
        segments = [(float(a), float(b)) for a, b in plan_data["segments_to_keep"]]
    else:
        plan = build_trim_plan(original, None, NON_TARGET_NOISE_THRESHOLD_DB, NON_TARGET_MIN_DURATION_SEC, NON_TARGET_PAD_SEC, args.work_dir)
        plan_data = asdict(plan); plan_data["segments_to_keep"] = [list(pair) for pair in plan.segments_to_keep]
        plan_path.write_text(json.dumps(plan_data, ensure_ascii=False, indent=2), encoding="utf-8")
        segments = plan.segments_to_keep
    if not segments: raise RuntimeError("Canary original retained no speech")
    audio = args.work_dir / "review.ogg"
    if not audio.exists(): SourceProcessingWorker._create_review_audio(original, audio, segments)
    transcript_path = args.work_dir / "transcript.txt"
    title_path = args.work_dir / "title.txt"
    if not transcript_path.exists() or not title_path.exists():
        transcript, title = analyze_review_audio(client, worker_token, audio)
        transcript_path.write_text(transcript, encoding="utf-8")
        title_path.write_text(title, encoding="utf-8")
    transcript = transcript_path.read_text(encoding="utf-8").strip()
    srt = args.work_dir / "subtitles.srt"
    if not srt.exists(): generate_srt_from_trim_segments(input_file=original, segments=segments, output_path=srt, work_dir=args.work_dir / "subtitle-work", api_key=key, log_dir=args.work_dir)
    print(json.dumps({"source_id": args.source_id, "title": title_path.read_text(encoding="utf-8").strip(), "transcript_chars": len(transcript), "srt_bytes": srt.stat().st_size, "segments": len(segments)}, ensure_ascii=False))
    return 0


if __name__ == "__main__": raise SystemExit(main())
