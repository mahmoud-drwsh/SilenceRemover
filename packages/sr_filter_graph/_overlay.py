"""Overlay filter chain builders.

Pure functions that generate FFmpeg filter graph suffixes for logo and title burn-ins.
"""


def _has_logo_overlay(logo_enabled: bool) -> bool:
    """Check if logo overlay should be enabled.
    
    Args:
        logo_enabled: Raw flag from caller
        
    Returns:
        Boolean indicating whether to include logo overlay
    """
    return bool(logo_enabled)


def _overlay_suffix_after_concat(
    *,
    title_overlay_y: int | None,
    logo_enabled: bool,
    logo_margin_px: int = 0,
    logo_alpha: float = 1.0,
) -> str:
    """Build overlay filter chain suffix for logo and/or title burn-ins.
    
    Applied after concat `[outv][outa]`: logo is composited on base video first,
    then title PNG is overlaid on top at the specified y position.
    
    The output is always normalized to NV12 format for hardware encoder compatibility.
    
    Args:
        title_overlay_y: Y position for title overlay (None = no title)
        logo_enabled: Whether to include logo overlay
        logo_margin_px: Margin in pixels for logo positioning (default: 0)
        logo_alpha: Alpha gain for logo transparency (default: 1.0 = opaque)
        
    Returns:
        Filter graph suffix string (starts with ";" if non-empty)
        
    Raises:
        ValueError: If both title and logo are disabled
    """
    has_title = title_overlay_y is not None
    has_logo = _has_logo_overlay(logo_enabled)
    if not has_title and not has_logo:
        return ""
    parts: list[str] = []
    base_label = "outv"
    logo_stream_idx = 2 if has_title else 1
    if has_logo:
        m = int(logo_margin_px)
        aa = float(logo_alpha)
        logo_out = "outv_logo"
        parts.append(
            f"[{logo_stream_idx}:v]format=rgba,colorchannelmixer=aa={aa}"
            f"[ov_logo];"
            f"[{base_label}][ov_logo]overlay=W-w-{m}:{m}:shortest=1[{logo_out}]"
        )
        base_label = logo_out
    if has_title:
        oy = int(title_overlay_y)  # type: ignore[arg-type]
        title_out = "outv_title"
        parts.append(
            f"[1:v]format=rgba[ov_title];[{base_label}][ov_title]overlay=0:{oy}:shortest=1[{title_out}]"
        )
        base_label = title_out
    # Normalize the post-overlay graph to a QSV-friendly software format.
    parts.append(f"[{base_label}]format=nv12[outv]")
    return ";" + ";".join(parts)
