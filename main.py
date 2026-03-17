#!/usr/bin/env python3
import sys
import traceback
from pathlib import Path
from typing import Optional

# Load .env file BEFORE any imports that might use config
from dotenv import load_dotenv
load_dotenv()

# Ensure project root (where this file lives) is on sys.path so `src` package is importable
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli import parse_args, fail, require_tools, require_input_dir, require_videos_in
from src.config import (
    VIDEO_EXTENSIONS,
    COMPLETED_DIR,
)
from src.paths import (
    sibling_dir,
    create_temp_subdirs,
    get_snippet_path,
    get_transcript_path,
    get_title_path,
    get_completed_path,
    is_transcript_done,
    is_title_done,
    is_completed,
    mark_completed,
    resolve_output_basename,
)
from src.trim import trim_single_video, create_silence_removed_audio
from src.content import transcribe_media, generate_title


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


# --- Main processing flow ---


def run_transcription_phase(
    video_path: Path,
    temp_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    api_key: str,
) -> bool:
    """Phase 1: Create snippet and transcribe it to temp/transcript/{basename}.txt."""
    basename = video_path.stem
    snippet_path = get_snippet_path(temp_dir, basename)

    if is_transcript_done(temp_dir, basename):
        print(f"Phase 1 already done for {video_path.name}, skipping transcription.")
        return True

    try:
        print(f"\n[1/3] Creating snippet (first 5 min, silence-removed): {video_path.name}")
        create_silence_removed_audio(
            input_file=video_path,
            output_audio_path=snippet_path,
            temp_dir=temp_dir,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
            target_length=None,
            max_duration=300,
        )

        print(f"\n[1/3] Transcribing: {snippet_path.name}")
        transcribe_media(
            media_path=snippet_path,
            temp_dir=temp_dir,
            api_key=api_key,
            basename=basename,
        )

        print(f"\n✓ Phase 1 (transcription) done: {video_path.name}")
        return True
    except Exception as e:
        print(f"\n✗ Phase 1 error for {video_path.name}: {e}", file=sys.stderr)
        traceback.print_exc()
        return False


def run_title_phase(
    video_path: Path,
    temp_dir: Path,
    api_key: str,
) -> bool:
    """Phase 2: Generate title from transcript to temp/title/{basename}.txt."""
    basename = video_path.stem

    if not is_transcript_done(temp_dir, basename):
        print(f"No transcript for {video_path.name}, skipping title phase.")
        return False

    if is_title_done(temp_dir, basename):
        print(f"Phase 2 already done for {video_path.name}, skipping title generation.")
        return True

    try:
        print(f"\n[2/3] Generating title for: {video_path.name}")
        generate_title(
            temp_dir=temp_dir,
            api_key=api_key,
            basename=basename,
        )

        print(f"\n✓ Phase 2 (title generation) done: {video_path.name}")
        return True
    except Exception as e:
        print(f"\n✗ Phase 2 error for {video_path.name}: {e}", file=sys.stderr)
        traceback.print_exc()
        return False


def run_output_phase(
    video_path: Path,
    output_dir: Path,
    temp_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
) -> bool:
    """Phase 3: Full video trim with silence removal, using title for output filename."""
    basename = video_path.stem

    if is_completed(temp_dir, basename):
        print(f"Phase 3 already done for {video_path.name}, skipping.")
        return True

    if not is_title_done(temp_dir, basename):
        print(f"No title for {video_path.name}, skipping output phase.")
        return False

    try:
        title = get_title_path(temp_dir, basename).read_text(encoding="utf-8").strip()
        if not title:
            print(f"Empty title for {video_path.name}, skipping output phase.")
            return False

        chosen_basename = resolve_output_basename(title, output_dir)
        print(f"\n[3/3] Creating final output: {video_path.name} -> {chosen_basename}.mp4")
        trim_single_video(
            input_file=video_path,
            output_dir=output_dir,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
            target_length=target_length,
            output_basename=chosen_basename,
        )
        mark_completed(temp_dir, basename)
        print(f"\n✓ Phase 3 (output) done: {video_path.name}")
        return True
    except Exception as e:
        print(f"\n✗ Phase 3 error for {video_path.name}: {e}", file=sys.stderr)
        traceback.print_exc()
        return False


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)

    require_tools("ffmpeg", "ffprobe")
    require_input_dir(input_dir)
    require_videos_in(input_dir)

    from src.config import load_config, get_config, SIMPLE_DB, SIMPLE_MIN_DURATION

    try:
        load_config()
    except ValueError as e:
        fail(str(e))

    output_dir = sibling_dir(input_dir, "output")
    temp_dir = output_dir / "temp"
    create_temp_subdirs(temp_dir)

    config = get_config()
    if args.noise_threshold is not None:
        noise_threshold = args.noise_threshold
    elif args.target_length is not None:
        noise_threshold = SIMPLE_DB
    else:
        noise_threshold = config["NOISE_THRESHOLD"]

    if args.min_duration is not None:
        min_duration = args.min_duration
    elif args.target_length is not None:
        min_duration = SIMPLE_MIN_DURATION
    else:
        min_duration = config["MIN_DURATION"]

    pad_sec = config["PAD"]
    api_key = config["OPENROUTER_API_KEY"]

    videos = sorted(p for p in input_dir.iterdir() if is_video_file(p))
    if not videos:
        print(f"No video files found in '{input_dir}'")
        return

    print(f"Found {len(videos)} video file(s)")
    print(f"Input: {input_dir}")
    print(f"Output: {output_dir}")
    print(f"Temp: {temp_dir}")
    print("-" * 60)

    # Phase 1: Transcription
    for i, video_file in enumerate(videos, 1):
        print(f"\n{'='*60}")
        print(f"[1/3][{i}/{len(videos)}] Transcription: {video_file.name}")
        print(f"{'='*60}")
        run_transcription_phase(
            video_path=video_file,
            temp_dir=temp_dir,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
            api_key=api_key,
        )

    # Phase 2: Title generation
    for i, video_file in enumerate(videos, 1):
        print(f"\n{'='*60}")
        print(f"[2/3][{i}/{len(videos)}] Title Generation: {video_file.name}")
        print(f"{'='*60}")
        run_title_phase(
            video_path=video_file,
            temp_dir=temp_dir,
            api_key=api_key,
        )

    # Phase 3: Final output
    for i, video_file in enumerate(videos, 1):
        print(f"\n{'='*60}")
        print(f"[3/3][{i}/{len(videos)}] Final Output: {video_file.name}")
        print(f"{'='*60}")
        run_output_phase(
            video_path=video_file,
            output_dir=output_dir,
            temp_dir=temp_dir,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
            target_length=args.target_length,
        )

    # Count completed videos
    completed_dir = temp_dir / COMPLETED_DIR
    completed = sum(1 for p in completed_dir.iterdir() if p.is_file())
    print(f"\n{'='*60}")
    print("Processing complete!")
    print(f"Completed: {completed}/{len(videos)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
