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


def collect_video_files(input_dir: Path) -> list[Path]:
    """Collect supported video files from a directory."""
    return sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)


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
        description="Three-phase pipeline: 1) Transcription, 2) Title generation, 3) Final output with silence removal"
    )
    parser.add_argument("input_dir", type=str, help="Input directory (raw videos)")
    parser.add_argument(
        "--target-length",
        type=_positive_float,
        help="Target length in seconds for final output (Phase 3)",
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
        "--llm-only",
        action="store_true",
        help=(
            "Transcription and title generation only (phases 1–2): no final video output, "
            "results printed to the console; hardware encoder probe is skipped. "
            "Appends per-video titles to output/temp/titles.txt as each title is ready."
        ),
    )
    return parser.parse_args()
