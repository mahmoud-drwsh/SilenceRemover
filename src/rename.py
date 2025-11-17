"""Video renaming functionality (copies trimmed files into output directory)."""

import shutil
import time
from pathlib import Path
from typing import Optional

_COPY_SLEEP_SEC = 1.0


def _sanitize_filename(name: str) -> str:
    cleaned = "".join(c for c in name if c not in "\0\n\r\t").strip().strip('"').strip("'")
    for ch in ["/", "\\", ":", "*", "?", "\"", "<", ">", "|"]:
        cleaned = cleaned.replace(ch, " ")
    return (" ".join(cleaned.split()) or "untitled")[:200]


def _copy_until_success(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            shutil.copyfile(src, dest)
            return
        except PermissionError as exc:
            print(f"Copy failed ({exc}). Retrying in {_COPY_SLEEP_SEC}s...")
            time.sleep(_COPY_SLEEP_SEC)
        except FileNotFoundError:
            raise FileNotFoundError(f"Source file not found: {src}") from None
        except OSError:
            raise


def rename_single_video_in_place(video_path: Path, temp_dir: Path, output_dir: Path) -> None:
    """Copy trimmed video from temp_dir into output_dir using the generated title."""
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
    
    print(f"Copying renamed file: {video_path.name} -> {dest.name}")
    _copy_until_success(video_path, dest)

