"""Video renaming functionality."""

import shutil
import time
from pathlib import Path
from typing import Optional


_RENAME_ATTEMPTS = 5
_RENAME_SLEEP_SEC = 0.75
_DELETE_ATTEMPTS = 5
_DELETE_SLEEP_SEC = 0.75


def _sanitize_filename(name: str) -> str:
    cleaned = "".join(c for c in name if c not in "\0\n\r\t").strip().strip('"').strip("'")
    for ch in ["/", "\\", ":", "*", "?", "\"", "<", ">", "|"]:
        cleaned = cleaned.replace(ch, " ")
    return (" ".join(cleaned.split()) or "untitled")[:200]


def _attempt_rename_with_retries(src: Path, dest: Path) -> bool:
    for attempt in range(1, _RENAME_ATTEMPTS + 1):
        try:
            src.replace(dest)
            return True
        except PermissionError as exc:
            if attempt == _RENAME_ATTEMPTS:
                print(
                    f"Rename attempt {attempt}/{_RENAME_ATTEMPTS} failed with permission error: {exc}."
                )
                break
            print(
                f"Rename attempt {attempt}/{_RENAME_ATTEMPTS} failed (permission denied). "
                f"Retrying in {_RENAME_SLEEP_SEC}s..."
            )
            time.sleep(_RENAME_SLEEP_SEC)
        except OSError:
            raise
    return False


def _unlink_with_retries(path: Path) -> None:
    for attempt in range(1, _DELETE_ATTEMPTS + 1):
        try:
            path.unlink()
            return
        except PermissionError as exc:
            if attempt == _DELETE_ATTEMPTS:
                raise
            print(
                f"Failed to remove '{path.name}' (attempt {attempt}/{_DELETE_ATTEMPTS}). "
                f"Retrying in {_DELETE_SLEEP_SEC}s..."
            )
            time.sleep(_DELETE_SLEEP_SEC)


def _copy_then_delete(src: Path, dest: Path) -> None:
    if dest.exists():
        dest.unlink()
    shutil.copy2(src, dest)
    print(f"Copied '{src.name}' to '{dest.name}'. Attempting to delete original...")
    _unlink_with_retries(src)


def rename_single_video_in_place(video_path: Path, temp_dir: Path, output_dir: Path) -> None:
    """Rename a single video in place in output_dir using title from temp_dir."""
    # Resolve to absolute path to ensure file can be found
    video_path = video_path.resolve()
    
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    basename = video_path.stem
    title_file = temp_dir / f"{basename}.title.txt"
    
    new_base: Optional[str] = None
    if title_file.exists():
        raw = title_file.read_text(encoding="utf-8").strip()
        if raw:
            new_base = _sanitize_filename(raw)
    
    if not new_base:
        new_base = _sanitize_filename(basename)
    
    # Check for duplicates in output_dir and append _N suffix if needed
    candidate = new_base
    k = 1
    while (output_dir / f"{candidate}{video_path.suffix}").exists():
        candidate = f"{new_base}_{k}"
        k += 1
    
    dest = output_dir / f"{candidate}{video_path.suffix}"
    dest = dest.resolve()
    
    if video_path == dest:
        print(f"File already has correct name: {video_path.name}")
        return
    
    print(f"Renaming: {video_path.name} -> {dest.name}")
    if _attempt_rename_with_retries(video_path, dest):
        return
    
    print("Rename attempts exhausted. Falling back to copy + delete strategy...")
    _copy_then_delete(video_path, dest)

