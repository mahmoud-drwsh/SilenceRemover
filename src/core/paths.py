"""Path construction and tracking utilities."""

import hashlib
from datetime import datetime
from pathlib import Path

from src.core.constants import (
    AUDIO_FILE_EXT,
    COMPLETED_DIR,
    FONTS_DIR,
    SCRIPTS_DIR,
    SILENCE_CACHE_DIR,
    SNIPPET_DIR,
    TEXT_FILE_EXT,
    TITLE_DIR,
    TITLE_OVERLAYS_DIR,
    TRANSCRIPT_DIR,
    VIDEO_PROCESSING_DIR,
)
from sr_filename import sanitize_filename

__all__ = [
    "sibling_dir",
    "create_temp_subdirs",
    "get_snippet_path",
    "get_transcript_path",
    "get_title_path",
    "get_font_cache_path",
    "get_title_overlay_path",
    "get_completed_path",
    "is_transcript_done",
    "is_title_done",
    "is_completed",
    "is_completed_with_title",
    "mark_completed",
    "compute_title_hash",
    "resolve_output_basename",
    "get_processing_video_path",
]


def sibling_dir(base_dir: Path, name: str) -> Path:
    d = base_dir.parent / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_temp_subdirs(temp_dir: Path) -> None:
    for subdir in [
        SNIPPET_DIR,
        TRANSCRIPT_DIR,
        TITLE_DIR,
        COMPLETED_DIR,
        SCRIPTS_DIR,
        SILENCE_CACHE_DIR,
        FONTS_DIR,
        TITLE_OVERLAYS_DIR,
        VIDEO_PROCESSING_DIR,
    ]:
        (temp_dir / subdir).mkdir(parents=True, exist_ok=True)


def get_snippet_path(temp_dir: Path, basename: str) -> Path:
    return temp_dir / SNIPPET_DIR / f"{basename}{AUDIO_FILE_EXT}"


def get_transcript_path(temp_dir: Path, basename: str) -> Path:
    return temp_dir / TRANSCRIPT_DIR / f"{basename}{TEXT_FILE_EXT}"


def get_title_path(temp_dir: Path, basename: str) -> Path:
    return temp_dir / TITLE_DIR / f"{basename}{TEXT_FILE_EXT}"


def get_font_cache_path(temp_dir: Path) -> Path:
    return temp_dir / FONTS_DIR


def get_title_overlay_path(temp_dir: Path, basename: str) -> Path:
    return temp_dir / TITLE_OVERLAYS_DIR / f"{basename}.png"


def get_completed_path(temp_dir: Path, basename: str) -> Path:
    return temp_dir / COMPLETED_DIR / f"{basename}{TEXT_FILE_EXT}"


def is_transcript_done(temp_dir: Path, basename: str) -> bool:
    path = get_transcript_path(temp_dir, basename)
    if not path.exists():
        return False
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeDecodeError):
        return False


def is_title_done(temp_dir: Path, basename: str) -> bool:
    return get_title_path(temp_dir, basename).exists()


def is_completed(temp_dir: Path, basename: str) -> bool:
    return get_completed_path(temp_dir, basename).exists()


def is_completed_with_title(temp_dir: Path, basename: str) -> tuple[bool, str | None]:
    path = get_completed_path(temp_dir, basename)
    if not path.exists():
        return (False, None)
    try:
        lines = path.read_text(encoding="utf-8").strip().split('\n')
        if len(lines) >= 2:
            return (True, lines[1])
        return (True, None)
    except (OSError, UnicodeDecodeError):
        return (False, None)


def get_completed_output_filename(temp_dir: Path, basename: str) -> str | None:
    """Get the output filename stored in completion marker (line 3), if any."""
    path = get_completed_path(temp_dir, basename)
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8").strip().split('\n')
        if len(lines) >= 3 and lines[2]:
            return lines[2]
        return None
    except (OSError, UnicodeDecodeError):
        return None


def compute_title_hash(title_text: str) -> str:
    return hashlib.sha256(title_text.encode('utf-8')).hexdigest()[:16]


def mark_completed(temp_dir: Path, basename: str, title_hash: str | None = None, output_filename: str | None = None) -> None:
    path = get_completed_path(temp_dir, basename)
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat()
    content = f"{timestamp}\n{title_hash or ''}\n{output_filename or ''}"
    path.write_text(content, encoding="utf-8")


def resolve_output_basename(title: str, output_dir: Path) -> str:
    base = sanitize_filename(title)
    candidate = base
    k = 0
    while (output_dir / f"{candidate}.mp4").exists():
        k += 1
        candidate = f"{base}_{k}"
    return candidate


def get_processing_video_path(temp_dir: Path, basename: str) -> Path:
    return temp_dir / VIDEO_PROCESSING_DIR / f"{basename}.mp4"
