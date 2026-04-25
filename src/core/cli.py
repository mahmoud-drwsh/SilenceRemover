"""CLI argument parsing and validation utilities."""

import argparse
import shutil
import sys
from pathlib import Path

from src.core.fs_utils import is_file_locked

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
    NON_TARGET_PAD_SEC,
    TARGET_SEARCH_BASE_PADDING_SEC,
    TARGET_SEARCH_HIGH_DB,
    TARGET_SEARCH_LOW_DB,
    TARGET_SEARCH_MIN_SILENCE_LEN_SEC,
    TITLE_FONT_DEFAULT,
    VIDEO_EXTENSIONS,
)


def fail(message: str) -> None:
    """Exit with error code."""
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
    """Collect supported video files from a directory.

    On Windows, files locked by another process (for example OBS still writing)
    are skipped so they do not enter the pipeline run.
    """
    video_files = []
    locked_video_files = []
    for p in input_dir.iterdir():
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if is_file_locked(p):
            locked_video_files.append(p)
            continue
        video_files.append(p)

    if locked_video_files:
        print(
            "Skipping locked input video(s) still being recorded on Windows: "
            + ", ".join(path.name for path in sorted(locked_video_files))
        )

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
        description="Phase-0-to-10 pipeline: 0) Trim Script Generation, 1) Snippet Creation, 2) Transcription, 3) Title Generation, 4) Audio Upload, 5) Title Overlay Generation, 6) Logo Overlay Preparation, 7) Final Video Encode, 8) Video Reconciliation, 9) Video Upload, 10) Tag Promotion"
    )
    parser.add_argument("input_dir", type=str, help="Input directory (raw videos)")
    parser.add_argument(
        "--target-length",
        type=_positive_float,
        help=(
            "Target length in seconds for final output (Phase 7). Uses fixed internal search "
            f"parameters: threshold {TARGET_SEARCH_LOW_DB}..{TARGET_SEARCH_HIGH_DB} dB, "
            f"min silence {TARGET_SEARCH_MIN_SILENCE_LEN_SEC}s, base padding {TARGET_SEARCH_BASE_PADDING_SEC}s."
        ),
    )
    parser.add_argument(
        "--non-target-noise-threshold",
        type=float,
        default=None,
        help=(
            "Silence detection threshold in dB for non-target mode. "
            f"Ignored when --target-length is set; non-target default is {NON_TARGET_NOISE_THRESHOLD_DB}."
        ),
    )
    parser.add_argument(
        "--non-target-min-duration",
        type=_positive_float,
        default=None,
        help=(
            "Minimum silence duration in seconds for non-target mode. "
            f"Ignored when --target-length is set; non-target default is {NON_TARGET_MIN_DURATION_SEC}."
        ),
    )
    parser.add_argument(
        "--non-target-pad-sec",
        type=_positive_float,
        default=None,
        help=(
            "Padding to keep around retained segments in seconds for non-target mode. "
            f"Ignored when --target-length is set; non-target default is {NON_TARGET_PAD_SEC:.1f} seconds."
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
        "--encoder",
        type=str,
        choices=["QSV", "AMF", "X265"],
        default="X265",
        help="Video encoder: QSV (Intel QuickSync), AMF (AMD), or X265 (software)"
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
            "Enable Media Manager integration for Phase-0-to-10 workflow: "
            "audio upload, title sync, and video delivery. "
            "Requires MEDIA_MANAGER_URL environment variable."
        ),
    )
    parser.add_argument(
        "--skip-shorter-than",
        type=_positive_float,
        default=30.0,
        help=(
            "Minimum video duration in seconds (preflight input screening). Videos shorter than this "
            "are moved to input/ignored/ and skipped. Default: 30.0."
        ),
    )
    return parser.parse_args()
