#!/usr/bin/env python3
import argparse
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ogv", ".ts", ".m2ts"
}


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def sanitize_filename(name: str) -> str:
    # Remove path separators and disallowed characters for macOS/Linux
    cleaned = "".join(c for c in name if c not in "\0\n\r\t")
    cleaned = cleaned.strip().strip('"').strip("'")
    # Replace problematic characters
    for ch in ["/", "\\", ":", "*", "?", "\"", "<", ">", "|"]:
        cleaned = cleaned.replace(ch, " ")
    # Collapse whitespace
    cleaned = " ".join(cleaned.split())
    return cleaned[:200] if cleaned else "untitled"


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Copy original files to a 'renamed' folder using generated titles.",
        epilog="""
Examples:
  uv run python rename_from_titles.py /Users/mahmoud/Desktop/VIDS
        """,
    )
    parser.add_argument("input_dir", help="Input directory containing original videos")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        print(f"Error: '{input_dir}' is not a directory", file=sys.stderr)
        sys.exit(1)

    base_parent = input_dir.parent
    temp_dir = base_parent / "temp"
    renamed_dir = base_parent / "renamed"
    renamed_dir.mkdir(parents=True, exist_ok=True)

    videos = sorted(p for p in input_dir.iterdir() if is_video_file(p))
    if not videos:
        print(f"No video files found in '{input_dir}'")
        return

    print(f"Found {len(videos)} file(s). Writing to: {renamed_dir}")

    seen_names = set()

    for i, video in enumerate(videos, 1):
        basename = video.stem
        title_file = temp_dir / f"{basename}.title.txt"
        new_base = None
        if title_file.exists():
            raw = title_file.read_text(encoding="utf-8").strip()
            if raw:
                new_base = sanitize_filename(raw)

        if not new_base:
            # Fallback to original basename
            new_base = sanitize_filename(basename)

        # Ensure uniqueness
        candidate = new_base
        suffix = 1
        while candidate.lower() in seen_names or (renamed_dir / f"{candidate}{video.suffix}").exists():
            candidate = f"{new_base}-{suffix}"
            suffix += 1
        seen_names.add(candidate.lower())

        dest = renamed_dir / f"{candidate}{video.suffix}"
        print(f"[{i}/{len(videos)}] {video.name} -> {dest.name}")
        shutil.copy2(video, dest)

    print("Done.")


if __name__ == "__main__":
    main()


