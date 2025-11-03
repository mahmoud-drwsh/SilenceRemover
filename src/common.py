from pathlib import Path

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ogv", ".ts", ".m2ts"
}


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def sibling_dir(base_dir: Path, name: str) -> Path:
    d = base_dir.parent / name
    d.mkdir(parents=True, exist_ok=True)
    return d


