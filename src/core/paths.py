"""Path construction and tracking utilities."""

from pathlib import Path

from src.core.constants import (
    AUDIO_FILE_EXT,
    COMPLETED_DIR,
    FONTS_DIR,
    OVERLAY_DONE_DIR,
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
    "is_snippet_done",
    "is_title_done",
    "is_completed",
    "mark_completed",
    "resolve_output_basename",
    "get_processing_video_path",
    "get_overlay_done_path",
    "is_overlay_done",
    "mark_overlay_done",
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
        OVERLAY_DONE_DIR,
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


def is_snippet_done(temp_dir: Path, basename: str) -> bool:
    path = get_snippet_path(temp_dir, basename)
    if not path.exists():
        return False
    try:
        return path.stat().st_size > 0
    except OSError:
        return False


def is_completed(temp_dir: Path, basename: str) -> bool:
    return get_completed_path(temp_dir, basename).exists()


def get_completed_output_filename(temp_dir: Path, basename: str) -> str | None:
    """Get the output filename stored in completion marker."""
    path = get_completed_path(temp_dir, basename)
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if line.strip():
                return line.strip()
        return None
    except (OSError, UnicodeDecodeError):
        return None


def mark_completed(
    temp_dir: Path, basename: str, output_filename: str | None = None
) -> None:
    path = get_completed_path(temp_dir, basename)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = output_filename or ""
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


def get_overlay_done_path(temp_dir: Path, basename: str) -> Path:
    return temp_dir / OVERLAY_DONE_DIR / f"{basename}.txt"


def is_overlay_done(temp_dir: Path, basename: str) -> bool:
    """Check if overlay matches current title content.
    
    Returns True only if:
    1. Overlay marker exists
    2. Marker contains the same title as current title.txt
    
    If title has changed, overlay needs regeneration.
    """
    path = get_overlay_done_path(temp_dir, basename)
    if not path.exists():
        return False
    
    # Read current title
    title_path = get_title_path(temp_dir, basename)
    if not title_path.exists():
        return False
    
    try:
        current_title = title_path.read_text(encoding="utf-8").strip()
        stored_title = path.read_text(encoding="utf-8").strip()
        return current_title == stored_title
    except (OSError, UnicodeDecodeError):
        return False


def mark_overlay_done(temp_dir: Path, basename: str, title_text: str) -> None:
    """Mark overlay as done, storing the title content.
    
    The overlay is only considered "done" if it was generated with this
    specific title content. If title changes later, is_overlay_done()
    will return False, triggering regeneration.
    """
    path = get_overlay_done_path(temp_dir, basename)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(title_text, encoding="utf-8")
    except OSError:
        pass
