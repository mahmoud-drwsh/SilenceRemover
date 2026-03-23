"""Filter-graph graph helpers for audio/video concat workflows."""

from __future__ import annotations

from pathlib import Path

from src.core.constants import LOGO_OVERLAY_ALPHA, LOGO_OVERLAY_MARGIN_PX

def build_filter_graph_script(segment_count: int, filter_chains: str, concat_inputs: str, *, include_video: bool) -> str:
    """Build a complete ffmpeg concat filter graph."""
    if include_video:
        return f"{filter_chains}{concat_inputs}concat=n={segment_count}:v=1:a=1[outv][outa]"
    return f"{filter_chains}{concat_inputs}concat=n={segment_count}:v=0:a=1[outa]"


def build_audio_concat_filter_graph(
    segments_to_keep: list[tuple[float, float]],
    overlay_y: int | None = None,
) -> str:
    """Build audio-only concat graph from keep segments."""
    filter_chains = "".join(
        f"[0:a]atrim=start={segment_start}:end={segment_end},asetpts=PTS-STARTPTS[a{i}];"
        for i, (segment_start, segment_end) in enumerate(segments_to_keep)
    )
    concat_inputs = "".join(f"[a{i}]" for i in range(len(segments_to_keep)))
    return build_filter_graph_script(
        len(segments_to_keep),
        filter_chains,
        concat_inputs,
        include_video=False,
    )


def build_video_audio_concat_filter_graph(
    segments_to_keep: list[tuple[float, float]],
    overlay_y: int | None = None,
) -> str:
    """Build video+audio concat graph from keep segments."""
    filter_chains = "".join(
        (
            f"[0:v]trim=start={segment_start}:end={segment_end},setpts=PTS-STARTPTS[v{i}];"
            f"[0:a]atrim=start={segment_start}:end={segment_end},asetpts=PTS-STARTPTS[a{i}];"
        )
        for i, (segment_start, segment_end) in enumerate(segments_to_keep)
    )
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(segments_to_keep)))
    return build_filter_graph_script(
        len(segments_to_keep),
        filter_chains,
        concat_inputs,
        include_video=True,
    )


def _segment_audio_duration_sec(segment_start: float, segment_end: float) -> float:
    return max(1e-6, float(segment_end) - float(segment_start))


def build_video_lavfi_audio_concat_filter_graph(
    segments_to_keep: list[tuple[float, float]],
    overlay_y: int | None = None,
) -> str:
    """Video from input 0 + silent stereo audio from lavfi input 1 (per-segment `atrim` lengths)."""
    filter_chains = "".join(
        (
            f"[0:v]trim=start={segment_start}:end={segment_end},setpts=PTS-STARTPTS[v{i}];"
            f"[1:a]atrim=start=0:end={_segment_audio_duration_sec(segment_start, segment_end)},"
            f"asetpts=PTS-STARTPTS[a{i}];"
        )
        for i, (segment_start, segment_end) in enumerate(segments_to_keep)
    )
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(segments_to_keep)))
    return build_filter_graph_script(
        len(segments_to_keep),
        filter_chains,
        concat_inputs,
        include_video=True,
    )


def write_filter_graph_script(path: Path, filter_graph: str) -> Path:
    """Write filter graph text to a file and return the path."""
    path.write_text(filter_graph, encoding="utf-8")
    return path


def _escape_ffmpeg_single_quoted_path(value: str) -> str:
    """
    Escape a value for inclusion in a single-quoted FFmpeg filter argument.

    We currently only expect filesystem paths here; the main risk is a literal `'`
    character breaking the filter syntax.
    """
    # FFmpeg's filter parser is not the same as Python's or shell quoting, but
    # escaping single quotes is still the practical minimum for safety.
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _has_logo_overlay(logo_enabled: bool) -> bool:
    return bool(logo_enabled)


def _lavfi_input_index(*, has_title: bool, has_logo: bool) -> int:
    """Input index of `anullsrc` when optional title and/or logo PNGs are appended before it."""
    return 1 + (1 if has_title else 0) + (1 if has_logo else 0)


def _overlay_suffix_after_concat(
    *,
    title_overlay_y: int | None,
    logo_enabled: bool,
    logo_margin_px: int,
    logo_alpha: float = LOGO_OVERLAY_ALPHA,
) -> str:
    """Video burn-ins after concat `[outv][outa]`: logo on base first, then title PNG at y on top."""
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


def build_video_audio_concat_filter_graph_with_title_overlay(
    segments_to_keep: list[tuple[float, float]],
    overlay_y: int | None = None,
    *,
    logo_enabled: bool = False,
    logo_margin_px: int = LOGO_OVERLAY_MARGIN_PX,
    logo_alpha: float = LOGO_OVERLAY_ALPHA,
) -> str:
    """Trim/concat from input 0; optional title PNG at [1:v]; optional logo at [2:v] if title else [1:v]."""
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
    logo_margin_px: int = LOGO_OVERLAY_MARGIN_PX,
    logo_alpha: float = LOGO_OVERLAY_ALPHA,
) -> str:
    """Filter graph for short fallback encode: [0:v] main, optional [1:v]/[2:v] PNGs, output [outv]."""
    has_title = title_overlay_y is not None
    has_logo = _has_logo_overlay(logo_enabled)
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
    logo_margin_px: int = LOGO_OVERLAY_MARGIN_PX,
    logo_alpha: float = LOGO_OVERLAY_ALPHA,
) -> str:
    """Like `build_video_audio_concat_filter_graph_with_title_overlay` but silent audio from lavfi (last input)."""
    segment_count = len(segments_to_keep)
    has_title = overlay_y is not None
    has_logo = _has_logo_overlay(logo_enabled)
    lavfi_a = _lavfi_input_index(has_title=has_title, has_logo=has_logo)
    filter_chains = "".join(
        (
            f"[0:v]trim=start={segment_start}:end={segment_end},setpts=PTS-STARTPTS[v{i}];"
            f"[{lavfi_a}:a]atrim=start=0:end={_segment_audio_duration_sec(segment_start, segment_end)},"
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
