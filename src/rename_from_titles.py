from pathlib import Path
import shutil
from .common import sibling_dir, is_video_file


def _sanitize_filename(name: str) -> str:
    cleaned = "".join(c for c in name if c not in "\0\n\r\t").strip().strip('"').strip("'")
    for ch in ["/", "\\", ":", "*", "?", "\"", "<", ">", "|"]:
        cleaned = cleaned.replace(ch, " ")
    return (" ".join(cleaned.split()) or "untitled")[:200]


def run(input_dir: Path) -> None:
    input_dir = Path(input_dir)
    temp_dir = sibling_dir(input_dir, "temp")
    renamed_dir = sibling_dir(input_dir, "renamed")

    videos = sorted(p for p in input_dir.iterdir() if is_video_file(p))
    if not videos:
        print(f"No video files found in '{input_dir}'")
        return

    print(f"Found {len(videos)} file(s). Writing to: {renamed_dir}")
    seen = set()
    for i, video in enumerate(videos, 1):
        basename = video.stem
        title_file = temp_dir / f"{basename}.title.txt"
        new_base = None
        if title_file.exists():
            raw = title_file.read_text(encoding="utf-8").strip()
            if raw:
                new_base = _sanitize_filename(raw)
        if not new_base:
            new_base = _sanitize_filename(basename)

        candidate = new_base
        k = 1
        while (candidate.lower() in seen) or (renamed_dir / f"{candidate}{video.suffix}").exists():
            candidate = f"{new_base}-{k}"
            k += 1
        seen.add(candidate.lower())
        dest = renamed_dir / f"{candidate}{video.suffix}"
        print(f"[{i}/{len(videos)}] {video.name} -> {dest.name}")
        shutil.copy2(video, dest)

    print("Done.")


