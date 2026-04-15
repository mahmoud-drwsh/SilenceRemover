"""CLI argument parsing and validation utilities."""

import argparse
import ctypes
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

# Windows API constants for file lock detection
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
GENERIC_READ = 0x80000000
FILE_SHARE_NONE = 0x00000000
OPEN_EXISTING = 3
ERROR_SHARING_VIOLATION = 32
INVALID_HANDLE_VALUE = -1

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


def is_file_locked(file_path: Path) -> bool:
    """Check if file is locked by another process (Windows-only).

    Uses Windows CreateFileW API to attempt exclusive read access.
    If the file is open by another process (e.g., OBS recording), 
    it returns ERROR_SHARING_VIOLATION.

    Args:
        file_path: Path to video file to check

    Returns:
        True if file is locked by another process, False if accessible
    """
    try:
        handle = kernel32.CreateFileW(
            str(file_path),
            GENERIC_READ,
            FILE_SHARE_NONE,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            err = ctypes.get_last_error()
            return err == ERROR_SHARING_VIOLATION
        kernel32.CloseHandle(handle)
        return False
    except (OSError, IOError):
        return False


def collect_video_files(input_dir: Path) -> list[Path]:
    """Collect supported video files from a directory.

    Filters out files locked by another process (e.g., being recorded by OBS).
    All valid, accessible videos go through the pipeline - individual phases
    handle their own skip logic (snippet, title, encode, upload, etc.).
    """
    video_files = []
    for p in input_dir.iterdir():
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
            # Only filter out files locked by another process (e.g., OBS recording)
            if not is_file_locked(p):
                video_files.append(p)


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
        description="Nine-phase pipeline: 1) Snippet Creation, 2) Transcription, 3) Title Generation, 4) Audio Upload, 5) Overlay Generation, 6) Final Video Encode, 7) Video Reconciliation, 8) Video Upload, 9) Tag Promotion"
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
            "Enable Media Manager integration for 9-phase workflow: "
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
