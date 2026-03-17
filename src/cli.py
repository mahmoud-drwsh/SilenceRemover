"""CLI argument parsing and validation utilities."""

import argparse
import shutil
import sys
from pathlib import Path

__all__ = ["parse_args", "fail", "require_tools", "require_input_dir", "require_videos_in"]

# Import VIDEO_EXTENSIONS here to avoid circular imports
from src.constants import VIDEO_EXTENSIONS


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


def require_videos_in(input_dir: Path) -> None:
    """Check that input directory contains video files."""
    def is_video_file(path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS

    try:
        has_video = any(is_video_file(p) for p in input_dir.iterdir())
    except FileNotFoundError:
        has_video = False
    if not has_video:
        fail(f"No video files found in '{input_dir}'")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments and return namespace."""
    parser = argparse.ArgumentParser(
        description="Three-phase pipeline: 1) Transcription, 2) Title generation, 3) Final output with silence removal"
    )
    parser.add_argument("input_dir", type=str, help="Input directory (raw videos)")
    parser.add_argument(
        "--target-length",
        type=float,
        help="Target length in seconds for final output (Phase 3)",
    )
    parser.add_argument(
        "--noise-threshold",
        type=float,
        default=None,
        help="Silence detection threshold in dB (e.g. -55). Overrides config; with --target-length uses SIMPLE_DB if not set.",
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=None,
        help="Minimum silence duration in seconds (e.g. 0.5). Overrides config; with --target-length uses SIMPLE_MIN_DURATION if not set.",
    )
    return parser.parse_args()
