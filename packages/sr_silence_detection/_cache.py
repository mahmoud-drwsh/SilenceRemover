from __future__ import annotations
import json
from pathlib import Path


def _get_cache_path(temp_dir: Path, basename: str) -> Path:
    return temp_dir / "silence" / f"{basename}_edge.json"


def _threshold_to_filename_safe(threshold_db: float) -> str:
    """Convert threshold to filename-safe string.

    Examples:
        -55.0 -> "neg_55_0"
        -50.5 -> "neg_50_5"
    """
    # Handle negative thresholds
    if threshold_db < 0:
        abs_val = abs(threshold_db)
        # Format without decimal point issues
        if abs_val == int(abs_val):
            return f"neg_{int(abs_val)}_0"
        else:
            # Replace decimal point with underscore
            abs_str = str(abs_val).replace(".", "_")
            return f"neg_{abs_str}"
    else:
        # Positive thresholds (unlikely but handle)
        if threshold_db == int(threshold_db):
            return f"pos_{int(threshold_db)}_0"
        else:
            pos_str = str(threshold_db).replace(".", "_")
            return f"pos_{pos_str}"


def _encode_min_duration(min_duration: float) -> str:
    """Encode min_duration to filename-safe string with 3 decimal places.

    Examples:
        0.1 -> "0_100"
        0.375 -> "0_375"
        0.5 -> "0_500"
    """
    return f"{min_duration:.3f}".replace(".", "_")


def _encode_threshold(threshold: float) -> str:
    """Encode threshold (dB) to filename-safe string with 3 decimal places.

    Examples:
        -59.75 -> "neg_59_750"
        -55.0 -> "neg_55_000"
        30.0 -> "pos_30_000"
        -30.125 -> "neg_30_125"
    """
    if threshold < 0:
        return f"neg_{abs(threshold):.3f}".replace(".", "_")
    else:
        return f"pos_{threshold:.3f}".replace(".", "_")


def _get_primary_cache_path(
    temp_dir: Path,
    basename: str,
    min_duration: float,
    threshold_db: float,
) -> Path:
    """Get cache path for primary detection results.

    Filename format: {basename}_primary_{min_duration}_{threshold}.json
    Example: MyVideo_primary_0_375_neg_59_75.json (for min_duration=0.375, threshold=-59.75)
    """
    min_dur_str = _encode_min_duration(min_duration)
    thresh_str = _encode_threshold(threshold_db)
    return temp_dir / "silence" / f"{basename}_primary_{min_dur_str}_{thresh_str}.json"


def _is_cache_valid(cache_data: dict, input_file: Path, params: dict) -> bool:
    try:
        stat = input_file.stat()
        if cache_data.get("input_mtime") != stat.st_mtime:
            return False
        if cache_data.get("input_size") != stat.st_size:
            return False
        if cache_data.get("input_inode") != stat.st_ino:
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


def _is_primary_cache_valid(cache_data: dict, input_file: Path, params: dict) -> bool:
    """Validate primary detection cache against input file and parameters."""
    try:
        stat = input_file.stat()
        if cache_data.get("input_mtime") != stat.st_mtime:
            return False
        if cache_data.get("input_size") != stat.st_size:
            return False
        if cache_data.get("input_inode") != stat.st_ino:
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
        "input_inode": stat.st_ino,
        "edge_noise_threshold_db": edge_threshold,
        "edge_min_duration_sec": edge_min_duration,
        "edge_keep_sec": edge_keep_sec,
        "edge_starts": edge_starts,
        "edge_ends": edge_ends,
        "duration_sec": duration_sec,
    }

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, indent=2)


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
    cache_path = _get_primary_cache_path(temp_dir, basename, min_duration_sec, threshold_db)
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    params = {
        "threshold_db": threshold_db,
        "min_duration_sec": min_duration_sec,
    }

    if not _is_primary_cache_valid(cache_data, input_file, params):
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
    cache_path = _get_primary_cache_path(temp_dir, basename, min_duration_sec, threshold_db)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    stat = input_file.stat()
    cache_data = {
        "version": "1.0",
        "basename": basename,
        "input_mtime": stat.st_mtime,
        "input_size": stat.st_size,
        "input_inode": stat.st_ino,
        "threshold_db": threshold_db,
        "min_duration_sec": min_duration_sec,
        "duration_sec": duration_sec,
        "silence_starts": silence_starts,
        "silence_ends": silence_ends,
    }

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, indent=2)
