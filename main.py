#!/usr/bin/env python3
import argparse
import json
import os
import sys
import traceback
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

# Load .env file BEFORE any imports that might use config
from dotenv import load_dotenv
load_dotenv()

# Ensure project root (where this file lives) is on sys.path so `src` package is importable
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# No external SDK needed - using requests for OpenRouter API

from src.main_utils import VIDEO_EXTENSIONS
from src.trim import trim_single_video
from src.transcribe import transcribe_single_video
from src.rename import rename_single_video_in_place

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


# _require_openrouter() removed - validation now handled in src/env_config


# --- Processed videos tracking ---

def get_processed_vids_file(temp_dir: Path) -> Path:
    """Get the path to the processed videos tracking file."""
    return temp_dir / "_processed_vids.json"


def load_processed_videos(temp_dir: Path) -> dict[str, dict]:
    """Load the processed videos database. Returns dict mapping video_name -> info."""
    processed_file = get_processed_vids_file(temp_dir)
    if not processed_file.exists():
        return {}
    
    try:
        with open(processed_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, Exception) as e:
        print(f"Warning: Could not read processed videos file: {e}", file=sys.stderr)
        return {}


def save_processed_videos(temp_dir: Path, processed_videos: dict[str, dict]) -> None:
    """Save the processed videos database."""
    processed_file = get_processed_vids_file(temp_dir)
    try:
        with open(processed_file, "w", encoding="utf-8") as f:
            json.dump(processed_videos, f, indent=2, sort_keys=True)
    except Exception as e:
        print(f"Warning: Could not save processed videos file: {e}", file=sys.stderr)


def is_video_processed(video_path: Path, temp_dir: Path) -> bool:
    """Check if a video has already been processed by checking the tracking file."""
    processed_videos = load_processed_videos(temp_dir)
    video_name = video_path.name
    return video_name in processed_videos


def mark_video_as_processed(video_path: Path, temp_dir: Path) -> None:
    """Mark a video as processed by adding it to the tracking file."""
    processed_videos = load_processed_videos(temp_dir)
    video_name = video_path.name
    
    processed_videos[video_name] = {
        "processed_at": datetime.now().isoformat(),
    }
    
    save_processed_videos(temp_dir, processed_videos)


# --- Main processing flow ---

def process_single_video(
    video_path: Path,
    input_dir: Path,
    output_dir: Path,
    temp_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
    api_key: str,
    debug: bool = False,
) -> bool:
    """Process a single video: trim, transcribe, rename. Returns True on success, False on error."""
    # Check if video is already processed
    if is_video_processed(video_path, temp_dir):
        print(f"Video already processed, skipping: {video_path.name}")
        return True
    
    try:
        basename = video_path.stem
        
        # Step 1: Trim video
        print(f"\n[1/3] Trimming: {video_path.name}")
        trimmed_video = trim_single_video(
            input_file=video_path,
            output_dir=temp_dir,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
            target_length=target_length,
            debug=debug,
        )
        
        # Step 2: Transcribe from trimmed video
        print(f"\n[2/3] Transcribing: {trimmed_video.name}")
        transcript_path, title_path = transcribe_single_video(trimmed_video, temp_dir, api_key, basename)
        
        # Step 3: Rename trimmed video in place
        print(f"\n[3/3] Renaming: {trimmed_video.name}")
        rename_single_video_in_place(trimmed_video, temp_dir, output_dir)
        
        # Mark video as processed
        mark_video_as_processed(video_path, temp_dir)
        
        print(f"\n✓ Completed: {video_path.name}")
        return True
        
    except Exception as e:
        print(f"\n✗ Error processing {video_path.name}: {e}", file=sys.stderr)
        traceback.print_exc()
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Trim videos, transcribe, and rename in place")
    parser.add_argument("input_dir", type=str, help="Input directory containing videos")
    parser.add_argument("--target-length", type=float, help="Target length in seconds for trimming")
    parser.add_argument("--debug", action="store_true", help="Print detailed debug logs")
    
    args = parser.parse_args()
    
    global DEBUG
    DEBUG = args.debug
    
    input_dir = Path(args.input_dir)
    
    # Validate inputs
    _require_tools("ffmpeg", "ffprobe")
    _require_input_dir(input_dir)
    _require_videos_in(input_dir)
    
    # Load and validate configuration (this will fail if OPENROUTER_API_KEY is missing)
    from src.env_config import load_config
    try:
        config = load_config()
    except ValueError as e:
        _fail(str(e))
    
    # Setup directories
    output_dir = sibling_dir(input_dir, "output")
    temp_dir = sibling_dir(input_dir, "temp")
    
    # Extract configuration values
    noise_threshold = config["NOISE_THRESHOLD"]
    min_duration = config["MIN_DURATION"]
    pad_sec = config["PAD"]
    api_key = config["OPENROUTER_API_KEY"]
    
    # Get videos to process
    videos = sorted(p for p in input_dir.iterdir() if is_video_file(p))
    if not videos:
        print(f"No video files found in '{input_dir}'")
        return
    
    print(f"Found {len(videos)} video file(s) to process")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Temp directory: {temp_dir}")
    print("-" * 60)
    
    # Process each video
    success_count = 0
    error_count = 0
    
    for i, video_file in enumerate(videos, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{len(videos)}] Processing: {video_file.name}")
        print(f"{'='*60}")
        
        success = process_single_video(
            video_path=video_file,
            input_dir=input_dir,
            output_dir=output_dir,
            temp_dir=temp_dir,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
            target_length=args.target_length,
            api_key=api_key,
            debug=DEBUG,
        )
        
        if success:
            success_count += 1
        else:
            error_count += 1
    
    # Summary
    print(f"\n{'='*60}")
    print(f"Processing complete!")
    print(f"Success: {success_count}/{len(videos)}")
    print(f"Errors: {error_count}/{len(videos)}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()

