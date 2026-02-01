#!/usr/bin/env python3
import argparse
import json
import sys
import traceback
import shutil
from pathlib import Path
from typing import Optional

# Load .env file BEFORE any imports that might use config
from dotenv import load_dotenv
load_dotenv()

# Ensure project root (where this file lives) is on sys.path so `src` package is importable
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.main_utils import VIDEO_EXTENSIONS
from src.trim import trim_single_video, create_silence_removed_audio
from src.transcribe import transcribe_single_video
from src.rename import sanitize_filename

# Debug flag (set from CLI)
DEBUG = False


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def sibling_dir(base_dir: Path, name: str) -> Path:
    d = base_dir.parent / name
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- Early validation helpers ---

def _fail(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def _require_tools(*tools: str) -> None:
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        _fail(f"Required tool(s) not found on PATH: {', '.join(missing)}")


def _require_input_dir(input_dir: Path) -> None:
    if not input_dir.exists() or not input_dir.is_dir():
        _fail(f"Input directory does not exist: {input_dir}")


def _require_videos_in(input_dir: Path) -> None:
    try:
        has_video = any(is_video_file(p) for p in input_dir.iterdir())
    except FileNotFoundError:
        has_video = False
    if not has_video:
        _fail(f"No video files found in '{input_dir}'")


# --- data.json (output/data.json) ---

DATA_JSON_NAME = "data.json"


def get_data_path(output_dir: Path) -> Path:
    return output_dir / DATA_JSON_NAME


def load_data(output_dir: Path) -> dict[str, dict]:
    """Load data.json. Returns dict mapping video_name -> { transcript, title, completed }."""
    path = get_data_path(output_dir)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, Exception) as e:
        print(f"Warning: Could not read {path}: {e}", file=sys.stderr)
        return {}


def save_data(output_dir: Path, data: dict[str, dict]) -> None:
    path = get_data_path(output_dir)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Warning: Could not save {path}: {e}", file=sys.stderr)


def resolve_output_basename(title: str, output_dir: Path) -> str:
    """Sanitize title and resolve duplicate (Title.mp4, Title_1.mp4, ...). Returns basename without extension."""
    base = sanitize_filename(title)
    candidate = base
    k = 0
    while (output_dir / f"{candidate}.mp4").exists():
        k += 1
        candidate = f"{base}_{k}"
    return candidate


# --- Main processing flow ---

def run_phase1_for_video(
    video_path: Path,
    output_dir: Path,
    temp_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    api_key: str,
    debug: bool,
) -> bool:
    """Phase 1: silence-removed first 5 min audio -> transcribe -> title. Updates data.json. Returns True on success."""
    data = load_data(output_dir)
    video_name = video_path.name
    basename = video_path.stem

    if data.get(video_name) and data[video_name].get("transcript") and data[video_name].get("title"):
        print(f"Phase 1 already done for {video_name}, skipping.")
        return True

    try:
        # (1) Silence-removed audio, first 5 min only (one pass)
        snippet_path = temp_dir / f"{basename}_snippet.wav"
        print(f"\n[Phase 1] Creating snippet (first 5 min, silence-removed): {video_name}")
        create_silence_removed_audio(
            input_file=video_path,
            output_audio_path=snippet_path,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
            target_length=None,
            max_duration=300,
            debug=debug,
        )

        # (2) Transcribe snippet and generate title (writes to temp .txt and .title.txt)
        print(f"\n[Phase 1] Transcribing and generating title: {snippet_path.name}")
        transcript_path, title_path = transcribe_single_video(
            media_path=snippet_path,
            temp_dir=temp_dir,
            api_key=api_key,
            basename=basename,
        )

        transcript_text = transcript_path.read_text(encoding="utf-8").strip()
        title_text = title_path.read_text(encoding="utf-8").strip() if title_path.exists() else ""

        if video_name not in data:
            data[video_name] = {}
        data[video_name]["transcript"] = transcript_text
        data[video_name]["title"] = title_text
        data[video_name]["completed"] = False
        save_data(output_dir, data)
        print(f"\n✓ Phase 1 done: {video_name}")
        return True
    except Exception as e:
        print(f"\n✗ Phase 1 error for {video_name}: {e}", file=sys.stderr)
        traceback.print_exc()
        return False


def run_phase2_for_video(
    video_path: Path,
    output_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
    debug: bool,
) -> bool:
    """Phase 2: full video+audio trim with title as output basename. Sets completed=True. Returns True on success."""
    data = load_data(output_dir)
    video_name = video_path.name

    if not data.get(video_name):
        print(f"No data for {video_name}, skipping Phase 2.")
        return False
    if data[video_name].get("completed"):
        print(f"Already completed: {video_name}, skipping Phase 2.")
        return True
    title = data[video_name].get("title", "").strip()
    if not title:
        print(f"No title for {video_name}, skipping Phase 2.")
        return False

    try:
        chosen_basename = resolve_output_basename(title, output_dir)
        print(f"\n[Phase 2] Trimming with title: {video_name} -> {chosen_basename}.mp4")
        trim_single_video(
            input_file=video_path,
            output_dir=output_dir,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
            target_length=target_length,
            debug=debug,
            output_basename=chosen_basename,
        )
        data[video_name]["completed"] = True
        save_data(output_dir, data)
        print(f"\n✓ Phase 2 done: {video_name}")
        return True
    except Exception as e:
        print(f"\n✗ Phase 2 error for {video_name}: {e}", file=sys.stderr)
        traceback.print_exc()
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 1: silence-removed audio -> transcribe -> title (output/data.json). Phase 2: full video trim with title."
    )
    parser.add_argument("input_dir", type=str, help="Input directory (raw videos)")
    parser.add_argument("--target-length", type=float, help="Target length in seconds for final trim (Phase 2)")
    parser.add_argument("--debug", action="store_true", help="Print detailed debug logs")

    args = parser.parse_args()

    global DEBUG
    DEBUG = args.debug

    input_dir = Path(args.input_dir)

    _require_tools("ffmpeg", "ffprobe")
    _require_input_dir(input_dir)
    _require_videos_in(input_dir)

    from src.env_config import load_config
    try:
        config = load_config()
    except ValueError as e:
        _fail(str(e))

    output_dir = sibling_dir(input_dir, "output")
    temp_dir = sibling_dir(input_dir, "temp")

    noise_threshold = config["NOISE_THRESHOLD"]
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

    # Phase 1: silence-removed first 5 min audio -> transcribe -> title (per video in order)
    for i, video_file in enumerate(videos, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{len(videos)}] Phase 1: {video_file.name}")
        print(f"{'='*60}")
        run_phase1_for_video(
            video_path=video_file,
            output_dir=output_dir,
            temp_dir=temp_dir,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
            api_key=api_key,
            debug=DEBUG,
        )

    # Phase 2: full video+audio trim with title
    for i, video_file in enumerate(videos, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{len(videos)}] Phase 2: {video_file.name}")
        print(f"{'='*60}")
        run_phase2_for_video(
            video_path=video_file,
            output_dir=output_dir,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
            target_length=args.target_length,
            debug=DEBUG,
        )

    data = load_data(output_dir)
    completed = sum(1 for v in data.values() if isinstance(v, dict) and v.get("completed"))
    print(f"\n{'='*60}")
    print("Processing complete!")
    print(f"Completed: {completed}/{len(videos)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
