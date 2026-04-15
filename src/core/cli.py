"""CLI argument parsing and validation utilities."""

import argparse
import shutil
import sys
from pathlib import Path

__all__ = [
    "collect_video_files",
    "parse_args",
    "fail",
    "require_tools",
    "require_input_dir",
    "require_videos_in",
]

# Import VIDEO_EXTENSIONS here to avoid circular imports
from src.core.constants import (
    NON_TARGET_MIN_DURATION_SEC,
    NON_TARGET_NOISE_THRESHOLD_DB,
    TITLE_FONT_DEFAULT,
    TARGET_MIN_DURATION_SEC,
    TARGET_NOISE_THRESHOLD_DB,
    VIDEO_EXTENSIONS,
)


def fail(message: str) -> None:
    """Print error message and exit."""
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def require_tools(*tools: str) -> None:
    """Check that required tools are available on PATH."""
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        fail(f"Required tool(s) not found on PATH: {', '.join(missing)}")


def require_input_dir(input_dir: Path) -> None:
    """Check that input directory exists."""
    if not input_dir.exists() or not input_dir.is_dir():
        fail(f"Input directory does not exist: {input_dir}")


def is_file_stable(file_path: Path) -> bool:
    """Check if video file is stable (complete and readable) using ffprobe.

    Runs ffprobe to verify the file has valid video metadata.
    Returns True immediately if file is readable as video.
    Returns False if ffprobe fails (file incomplete/corrupt/locked).

    Args:
        file_path: Path to video file to check

    Returns:
        True if file is stable and readable, False otherwise
    """
    from src.ffmpeg.runner import run
    from sr_ffmpeg_cmd_builder import build_ffprobe_metadata_command

    try:
        cmd = build_ffprobe_metadata_command(file_path, "duration")
        result = run(cmd, capture_output=True, check=False, timeout=5)
        # ffprobe success + non-empty duration = stable file
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


def collect_video_files(input_dir: Path) -> list[Path]:
    """Collect supported video files from a directory.

    Filters out files that are still being written to (e.g., being recorded).
    Skips files that have already been processed (completion marker exists).
    """
    from src.core.paths import is_completed

    # Calculate temp_dir path (output/temp relative to input_dir)
    temp_dir = input_dir.parent / "output" / "temp"

    video_files = []
    skipped_completed_count = 0
    for p in input_dir.iterdir():
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
            basename = p.stem

            # Skip already completed files silently (no ffprobe needed)
            if is_completed(temp_dir, basename):
                skipped_completed_count += 1
                continue

            # Check stability only for new files
            if is_file_stable(p):
                video_files.append(p)
            else:
                print(f"Skipping file still being written: {p.name}")

    # Log total skipped completed files (if any)
    if skipped_completed_count > 0:
        print(f"Skipped {skipped_completed_count} already completed file(s)")

    return sorted(video_files)


def require_videos_in(input_dir: Path) -> None:
    """Check that input directory contains video files."""
    try:
        has_video = len(collect_video_files(input_dir)) > 0
    except FileNotFoundError:
        has_video = False
    if not has_video:
        fail(f"No video files found in '{input_dir}'")


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Must be a number, got '{value}'")

    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"Value must be greater than 0, got '{value}'")
    return parsed


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments and return namespace."""
    parser = argparse.ArgumentParser(
        description="Eight-phase pipeline: 1) Snippet Creation, 2) Transcription, 3) Title Generation, 4) Audio Upload, 5) Overlay Generation, 6) Final Video Encode, 7) Stage to Pending, 8) Publish Video"
    )
    parser.add_argument("input_dir", type=str, help="Input directory (raw videos)")
    parser.add_argument(
        "--target-length",
        type=_positive_float,
        help="Target length in seconds for final output (Phase 6)",
    )
    parser.add_argument(
        "--noise-threshold",
        type=float,
        default=None,
        help=(
            "Silence detection threshold in dB. Overrides config; with --target-length "
            f"it defaults to {TARGET_NOISE_THRESHOLD_DB}."
        ),
    )
    parser.add_argument(
        "--min-duration",
        type=_positive_float,
        default=None,
        help=(
            "Minimum silence duration in seconds. Overrides config. With --target-length, defaults to "
            f"{TARGET_MIN_DURATION_SEC}; otherwise {NON_TARGET_MIN_DURATION_SEC}."
        ),
    )
    parser.add_argument(
        "--title-font",
        type=str,
        default=TITLE_FONT_DEFAULT,
        help=(
            "Google Font family name used to render the title overlay band (downloaded on first use). "
            f"Defaults to {TITLE_FONT_DEFAULT}."
        ),
    )
    parser.add_argument(
        "--quick-test",
        action="store_true",
        help=(
            "Run full phases 1-8, but cap only final Phase 6 output encoding "
            "to the first 5 seconds for end-to-end smoke testing."
        ),
    )
    parser.add_argument(
        "--enable-title-overlay",
        action="store_true",
        help="Enable title overlay in final output.",
    )
    parser.add_argument(
        "--enable-logo-overlay",
        action="store_true",
        help="Enable logo overlay in final output (requires logo/logo.png).",
    )
    parser.add_argument(
        "--title-y-fraction",
        type=float,
        default=None,
        help=(
            "Title overlay Y position as fraction of video height (0.0-1.0). "
            "Default is 1/6 (0.167). 0.0 = top, 0.5 = middle."
        ),
    )
    parser.add_argument(
        "--title-height-fraction",
        type=float,
        default=None,
        help=(
            "Title banner height as fraction of video height (0.0-1.0). "
            "Default is 1/6 (0.167)."
        ),
    )
    parser.add_argument(
        "--enable-media-manager",
        action="store_true",
        help=(
            "Enable Media Manager integration for 8-phase workflow: "
            "audio upload, title sync, and video delivery. "
            "Requires MEDIA_MANAGER_URL environment variable."
        ),
    )
    parser.add_argument(
        "--skip-shorter-than",
        type=_positive_float,
        default=10.0,
        help=(
            "Minimum video duration in seconds (Phase 0). Videos shorter than this "
            "are moved to input/ignored/ and skipped. Default: 10.0. "
            "Skipped in quick-test mode."
        ),
    )
    return parser.parse_args()
