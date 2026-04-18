from __future__ import annotations
import json
from pathlib import Path


def _get_cache_path(temp_dir: Path, basename: str) -> Path:
    return temp_dir / "silence" / f"{basename}.json"


def _get_primary_cache_key(min_duration: float, threshold_db: float) -> str:
    """Build a stable in-file key for primary detection results.

    Examples:
        min_duration=0.375, threshold=-59.75 -> "d:0.375|t:-59.750"
    """
    return f"d:{min_duration:.3f}|t:{threshold_db:.3f}"


def _load_cache_data(cache_path: Path) -> dict | None:
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(cache_data, dict):
        return None

    return cache_data


def _write_cache_data(cache_path: Path, cache_data: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, indent=2)


def _build_file_signature(input_file: Path) -> dict:
    stat = input_file.stat()
    return {
        "input_mtime": stat.st_mtime,
        "input_size": stat.st_size,
        "input_inode": stat.st_ino,
    }


def _cache_matches_input(cache_data: dict, input_file: Path) -> bool:
    try:
        signature = _build_file_signature(input_file)
    except OSError:
        return False

    return (
        cache_data.get("input_mtime") == signature["input_mtime"]
        and cache_data.get("input_size") == signature["input_size"]
        and cache_data.get("input_inode") == signature["input_inode"]
    )


def _get_or_create_cache_data(cache_path: Path, basename: str, input_file: Path) -> dict:
    cache_data = _load_cache_data(cache_path)
    if cache_data is None or not _cache_matches_input(cache_data, input_file):
        cache_data = {
            "version": "2.0",
            "basename": basename,
            **_build_file_signature(input_file),
            "edge_cache": None,
            "primary_cache": {},
        }
    else:
        cache_data.setdefault("edge_cache", None)
        cache_data.setdefault("primary_cache", {})
    return cache_data


def _is_cache_valid(cache_root: dict, cache_data: dict, input_file: Path, params: dict) -> bool:
    try:
        if not _cache_matches_input(cache_root, input_file):
            return False
        if cache_data.get("edge_noise_threshold_db") != params.get("edge_threshold"):
            return False
        if cache_data.get("edge_min_duration_sec") != params.get("edge_min_duration"):
            return False
        if cache_data.get("edge_keep_sec") != params.get("edge_keep_sec"):
            return False
        return True
    except (OSError, KeyError):
        return False


def _is_primary_cache_valid(cache_root: dict, cache_data: dict, input_file: Path, params: dict) -> bool:
    """Validate primary detection cache against input file and parameters."""
    try:
        if not _cache_matches_input(cache_root, input_file):
            return False
        if cache_data.get("threshold_db") != params.get("threshold_db"):
            return False
        if cache_data.get("min_duration_sec") != params.get("min_duration_sec"):
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
    cache_root = _load_cache_data(cache_path)
    if cache_root is None:
        return None
    cache_data = cache_root.get("edge_cache")
    if not isinstance(cache_data, dict):
        return None

    params = {
        "edge_threshold": edge_threshold,
        "edge_min_duration": edge_min_duration,
        "edge_keep_sec": edge_keep_sec,
    }

    if not _is_cache_valid(cache_root, cache_data, input_file, params):
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
    cache_root = _get_or_create_cache_data(cache_path, basename, input_file)

    cache_root["edge_cache"] = {
        "edge_noise_threshold_db": edge_threshold,
        "edge_min_duration_sec": edge_min_duration,
        "edge_keep_sec": edge_keep_sec,
        "edge_starts": edge_starts,
        "edge_ends": edge_ends,
        "duration_sec": duration_sec,
    }

    _write_cache_data(cache_path, cache_root)


def get_cached_primary_detection(
    temp_dir: Path,
    basename: str,
    input_file: Path,
    threshold_db: float,
    min_duration_sec: float,
) -> tuple[list[float], list[float], float] | None:
    """Get cached primary detection results if valid.

    Args:
        temp_dir: Directory for cache storage
        basename: Base name for cache file identification
        input_file: Path to media file (used for cache validation)
        threshold_db: Silence threshold in dB
        min_duration_sec: Minimum silence duration in seconds

    Returns:
        Tuple of (silence_starts, silence_ends, duration_sec) or None if cache miss/invalid
    """
    cache_path = _get_cache_path(temp_dir, basename)
    cache_root = _load_cache_data(cache_path)
    if cache_root is None:
        return None
    primary_cache = cache_root.get("primary_cache")
    if not isinstance(primary_cache, dict):
        return None
    cache_data = primary_cache.get(_get_primary_cache_key(min_duration_sec, threshold_db))
    if not isinstance(cache_data, dict):
        return None

    params = {
        "threshold_db": threshold_db,
        "min_duration_sec": min_duration_sec,
    }

    if not _is_primary_cache_valid(cache_root, cache_data, input_file, params):
        return None

    try:
        return (
            cache_data["silence_starts"],
            cache_data["silence_ends"],
            cache_data["duration_sec"],
        )
    except KeyError:
        return None


def save_primary_detection(
    temp_dir: Path,
    basename: str,
    input_file: Path,
    silence_starts: list[float],
    silence_ends: list[float],
    duration_sec: float,
    threshold_db: float,
    min_duration_sec: float,
) -> None:
    """Save primary detection results to cache.

    Args:
        temp_dir: Directory for cache storage
        basename: Base name for cache file identification
        input_file: Path to media file (used for cache validation)
        silence_starts: List of silence start timestamps
        silence_ends: List of silence end timestamps
        duration_sec: Media duration in seconds
        threshold_db: Silence threshold in dB used for detection
        min_duration_sec: Minimum silence duration used for detection
    """
    cache_path = _get_cache_path(temp_dir, basename)
    cache_root = _get_or_create_cache_data(cache_path, basename, input_file)
    primary_cache = cache_root.setdefault("primary_cache", {})
    primary_cache[_get_primary_cache_key(min_duration_sec, threshold_db)] = {
        "threshold_db": threshold_db,
        "min_duration_sec": min_duration_sec,
        "duration_sec": duration_sec,
        "silence_starts": silence_starts,
        "silence_ends": silence_ends,
    }

    _write_cache_data(cache_path, cache_root)
