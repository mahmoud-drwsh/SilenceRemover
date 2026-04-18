"""Media domain package for silence detection and trimming."""

from src.media.silence_detector import (
    TRIM_TIMESTAMP_EPSILON_SEC,
    calculate_resulting_length,
    find_optimal_padding,
    normalize_timestamp,
    truncate_segments_to_max_length,
)
def trim_single_video(*args, **kwargs):
    from src.media.trim import trim_single_video as _trim_single_video

    return _trim_single_video(*args, **kwargs)


def prepare_video_overlays(*args, **kwargs):
    from src.media.trim import prepare_video_overlays as _prepare_video_overlays

    return _prepare_video_overlays(*args, **kwargs)


def prepare_title_overlay(*args, **kwargs):
    from src.media.trim import prepare_title_overlay as _prepare_title_overlay

    return _prepare_title_overlay(*args, **kwargs)


def prepare_logo_overlay(*args, **kwargs):
    from src.media.trim import prepare_logo_overlay as _prepare_logo_overlay

    return _prepare_logo_overlay(*args, **kwargs)


__all__ = [
    "TRIM_TIMESTAMP_EPSILON_SEC",
    "calculate_resulting_length",
    "find_optimal_padding",
    "normalize_timestamp",
    "truncate_segments_to_max_length",
    "trim_single_video",
    "prepare_video_overlays",
    "prepare_title_overlay",
    "prepare_logo_overlay",
]
