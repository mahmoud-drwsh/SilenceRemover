from __future__ import annotations
import json
from pathlib import Path


def _get_cache_path(temp_dir: Path, basename: str) -> Path:
    return temp_dir / "silence" / f"{basename}_edge.json"


def _is_cache_valid(cache_data: dict, input_file: Path, params: dict) -> bool:
    try:
        stat = input_file.stat()
        if cache_data.get("input_mtime") != stat.st_mtime:
            return False
        if cache_data.get("input_size") != stat.st_size:
            return False
        if cache_data.get("edge_noise_threshold_db") != params["edge_threshold"]:
            return False
        if cache_data.get("edge_min_duration_sec") != params["edge_min_duration"]:
            return False
        if cache_data.get("edge_keep_sec") != params["edge_keep_sec"]:
            return False
        return True
    except (OSError, KeyError):
        return False


def get_cached_edge_detection(
    temp_dir: Path,
    basename: str,
    input_file: Path,
    edge_threshold: float,
    edge_min_duration: float,
    edge_keep_sec: float,
) -> tuple[list[float], list[float], float] | None:
    cache_path = _get_cache_path(temp_dir, basename)
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    params = {
        "edge_threshold": edge_threshold,
        "edge_min_duration": edge_min_duration,
        "edge_keep_sec": edge_keep_sec,
    }

    if not _is_cache_valid(cache_data, input_file, params):
        return None

    try:
        return (
            cache_data["edge_starts"],
            cache_data["edge_ends"],
            cache_data["duration_sec"],
        )
    except KeyError:
        return None


def save_edge_detection(
    temp_dir: Path,
    basename: str,
    input_file: Path,
    edge_starts: list[float],
    edge_ends: list[float],
    duration_sec: float,
    edge_threshold: float,
    edge_min_duration: float,
    edge_keep_sec: float,
) -> None:
    cache_path = _get_cache_path(temp_dir, basename)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    stat = input_file.stat()
    cache_data = {
        "version": "1.0",
        "basename": basename,
        "input_mtime": stat.st_mtime,
        "input_size": stat.st_size,
        "edge_noise_threshold_db": edge_threshold,
        "edge_min_duration_sec": edge_min_duration,
        "edge_keep_sec": edge_keep_sec,
        "edge_starts": edge_starts,
        "edge_ends": edge_ends,
        "duration_sec": duration_sec,
    }

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, indent=2)
