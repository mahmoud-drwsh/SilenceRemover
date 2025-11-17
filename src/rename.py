"""Video renaming functionality."""

import time
from pathlib import Path
from typing import Optional


def _sanitize_filename(name: str) -> str:
    cleaned = "".join(c for c in name if c not in "\0\n\r\t").strip().strip('"').strip("'")
    for ch in ["/", "\\", ":", "*", "?", "\"", "<", ">", "|"]:
        cleaned = cleaned.replace(ch, " ")
    return (" ".join(cleaned.split()) or "untitled")[:200]


def _rename_until_success(src: Path, dest: Path) -> None:
    while True:
        try:
            src.replace(dest)
            return
        except PermissionError as exc:
            print(f"Rename failed ({exc}). Retrying in 1s...")
            time.sleep(1)
        except FileNotFoundError:
            raise FileNotFoundError(f"Source file not found: {src}") from None
        except OSError:
            raise


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
    _rename_until_success(video_path, dest)

