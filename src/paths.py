"""Path construction and tracking utilities."""

from datetime import datetime
from pathlib import Path

from src.constants import COMPLETED_DIR, SCRIPTS_DIR, SNIPPET_DIR, TITLE_DIR, TRANSCRIPT_DIR
from src.filename_sanitizer import sanitize_filename

__all__ = [
    "sibling_dir",
    "create_temp_subdirs",
    "get_snippet_path",
    "get_transcript_path",
    "get_title_path",
    "get_completed_path",
    "is_transcript_done",
    "is_title_done",
    "is_completed",
    "mark_completed",
    "resolve_output_basename",
]


def sibling_dir(base_dir: Path, name: str) -> Path:
    """Create a sibling directory to base_dir."""
    d = base_dir.parent / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_temp_subdirs(temp_dir: Path) -> None:
    """Create subdirectories in temp directory."""
    for subdir in [SNIPPET_DIR, TRANSCRIPT_DIR, TITLE_DIR, COMPLETED_DIR, SCRIPTS_DIR]:
        (temp_dir / subdir).mkdir(parents=True, exist_ok=True)


def get_snippet_path(temp_dir: Path, basename: str) -> Path:
    """Path to snippet audio file (first 5 min, silence-removed)."""
    return temp_dir / SNIPPET_DIR / f"{basename}.ogg"


def get_transcript_path(temp_dir: Path, basename: str) -> Path:
    """Path to transcript text file."""
    return temp_dir / TRANSCRIPT_DIR / f"{basename}.txt"


def get_title_path(temp_dir: Path, basename: str) -> Path:
    """Path to title text file."""
    return temp_dir / TITLE_DIR / f"{basename}.txt"


def get_completed_path(temp_dir: Path, basename: str) -> Path:
    """Path to completed timestamp file."""
    return temp_dir / COMPLETED_DIR / f"{basename}.txt"


def is_transcript_done(temp_dir: Path, basename: str) -> bool:
    """Check if transcription is already done."""
    return get_transcript_path(temp_dir, basename).exists()


def is_title_done(temp_dir: Path, basename: str) -> bool:
    """Check if title generation is already done."""
    return get_title_path(temp_dir, basename).exists()


def is_completed(temp_dir: Path, basename: str) -> bool:
    """Check if video processing is already completed."""
    return get_completed_path(temp_dir, basename).exists()


def mark_completed(temp_dir: Path, basename: str) -> None:
    """Mark video as completed with timestamp."""
    path = get_completed_path(temp_dir, basename)
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat()
    path.write_text(timestamp, encoding="utf-8")


def resolve_output_basename(title: str, output_dir: Path) -> str:
    """Sanitize title and resolve duplicate (Title.mp4, Title_1.mp4, ...). Returns basename without extension."""
    base = sanitize_filename(title)
    candidate = base
    k = 0
    while (output_dir / f"{candidate}.mp4").exists():
        k += 1
        candidate = f"{base}_{k}"
    return candidate
