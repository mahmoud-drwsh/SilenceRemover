"""Public API for FFmpeg filter graph building.

Pure functions that generate complete FFmpeg filter graph strings for various
concatenation and overlay workflows. All functions are deterministic and have
no side effects.
"""

from sr_filter_graph._concat import (
    build_audio_concat_filter_graph,
    build_filter_graph_script,
    build_video_audio_concat_filter_graph,
    build_video_lavfi_audio_concat_filter_graph,
)
from sr_filter_graph._core import _lavfi_input_index
from sr_filter_graph._overlay import _overlay_suffix_after_concat


def build_video_audio_concat_filter_graph_with_title_overlay(
    segments_to_keep: list[tuple[float, float]],
    overlay_y: int | None = None,
    *,
    logo_enabled: bool = False,
    logo_margin_px: int = 0,
    logo_alpha: float = 1.0,
) -> str:
    """Build video+audio concat graph with optional title and logo overlays.
    
    Creates a filter graph that:
    1. Trims and concatenates video/audio from input 0
    2. Optionally overlays a logo PNG at input 1 or 2
    3. Optionally overlays a title PNG at input 1 (or 2 if logo present)
    
    Input order when both overlays present:
    - 0: Main video
    - 1: Title PNG
    - 2: Logo PNG
    
    Args:
        segments_to_keep: List of (start, end) timestamps for segments to keep
        overlay_y: Y position for title banner overlay (None = no title)
        logo_enabled: Whether to include logo overlay
        logo_margin_px: Margin pixels for logo positioning (default: 0)
        logo_alpha: Alpha gain for logo transparency (default: 1.0 = opaque)
        
    Returns:
        Complete FFmpeg filter graph string
        
    Raises:
        ValueError: If both title and logo are disabled
    """
    segment_count = len(segments_to_keep)
    filter_chains = "".join(
        (
            f"[0:v]trim=start={segment_start}:end={segment_end},setpts=PTS-STARTPTS[v{i}];"
            f"[0:a]atrim=start={segment_start}:end={segment_end},asetpts=PTS-STARTPTS[a{i}];"
        )
        for i, (segment_start, segment_end) in enumerate(segments_to_keep)
    )
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(segment_count))
    suffix = _overlay_suffix_after_concat(
        title_overlay_y=overlay_y,
        logo_enabled=logo_enabled,
        logo_margin_px=logo_margin_px,
        logo_alpha=logo_alpha,
    )
    if not suffix:
        raise ValueError("title overlay and logo overlay cannot both be disabled for this graph builder")
    return f"{filter_chains}{concat_inputs}concat=n={segment_count}:v=1:a=1[outv][outa]{suffix}"


def build_minimal_encode_overlay_filter_complex(
    *,
    title_overlay_y: int | None,
    logo_enabled: bool,
    logo_margin_px: int = 0,
    logo_alpha: float = 1.0,
) -> str:
    """Build filter graph for short fallback encode with overlays.
    
    Creates a filter graph for minimal encode mode:
    - 0:v = Main video
    - 1:v = Title PNG (if has_title)
    - 2:v = Logo PNG (if has_logo and has_title, else 1:v)
    
    Output: [outv] for encoding.
    
    Args:
        title_overlay_y: Y position for title banner (None = no title)
        logo_enabled: Whether to include logo overlay
        logo_margin_px: Margin pixels for logo positioning (default: 0)
        logo_alpha: Alpha gain for logo transparency (default: 1.0 = opaque)
        
    Returns:
        FFmpeg filter complex string
        
    Raises:
        ValueError: If both title and logo are disabled
    """
    has_title = title_overlay_y is not None
    has_logo = logo_enabled
    if not has_title and not has_logo:
        raise ValueError("minimal overlay graph requires at least title or logo")
    parts: list[str] = []
    base_label = "0:v"
    if has_logo:
        m = int(logo_margin_px)
        logo_i = 2 if has_title else 1
        aa = float(logo_alpha)
        logo_out = "outv_logo"
        parts.append(
            f"[{logo_i}:v]format=rgba,colorchannelmixer=aa={aa}"
            f"[lg];"
            f"[{base_label}][lg]overlay=W-w-{m}:{m}:shortest=1[{logo_out}]"
        )
        base_label = logo_out
    if has_title:
        oy = int(title_overlay_y)  # type: ignore[arg-type]
        title_out = "outv_title"
        parts.append(
            f"[1:v]format=rgba[ov_title];[{base_label}][ov_title]overlay=0:{oy}:shortest=1[{title_out}]"
        )
        base_label = title_out
    parts.append(f"[{base_label}]format=nv12[outv]")
    return ";".join(parts)


def build_video_lavfi_audio_concat_filter_graph_with_title_overlay(
    segments_to_keep: list[tuple[float, float]],
    overlay_y: int | None = None,
    *,
    logo_enabled: bool = False,
    logo_margin_px: int = 0,
    logo_alpha: float = 1.0,
) -> str:
    """Build concat graph with lavfi audio and optional overlays.
    
    Like `build_video_audio_concat_filter_graph_with_title_overlay` but uses
    silent audio from lavfi (last input) instead of source audio.
    
    Input order when both overlays present:
    - 0: Main video
    - 1: Title PNG
    - 2: Logo PNG
    - 3: lavfi audio source
    
    Args:
        segments_to_keep: List of (start, end) timestamps for segments to keep
        overlay_y: Y position for title banner overlay (None = no title)
        logo_enabled: Whether to include logo overlay
        logo_margin_px: Margin pixels for logo positioning (default: 0)
        logo_alpha: Alpha gain for logo transparency (default: 1.0 = opaque)
        
    Returns:
        Complete FFmpeg filter graph string
        
    Raises:
        ValueError: If both title and logo are disabled
    """
    segment_count = len(segments_to_keep)
    has_title = overlay_y is not None
    has_logo = logo_enabled
    lavfi_a = _lavfi_input_index(has_title=has_title, has_logo=has_logo)
    filter_chains = "".join(
        (
            f"[0:v]trim=start={segment_start}:end={segment_end},setpts=PTS-STARTPTS[v{i}];"
            f"[{lavfi_a}:a]atrim=start=0:end={segment_end - segment_start},"
            f"asetpts=PTS-STARTPTS[a{i}];"
        )
        for i, (segment_start, segment_end) in enumerate(segments_to_keep)
    )
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(segment_count))
    suffix = _overlay_suffix_after_concat(
        title_overlay_y=overlay_y,
        logo_enabled=logo_enabled,
        logo_margin_px=logo_margin_px,
        logo_alpha=logo_alpha,
    )
    if not suffix:
        raise ValueError("title overlay and logo overlay cannot both be disabled for this graph builder")
    return f"{filter_chains}{concat_inputs}concat=n={segment_count}:v=1:a=1[outv][outa]{suffix}"
