"""Filter-graph graph helpers for audio/video concat workflows."""

from __future__ import annotations

from pathlib import Path

def build_filter_graph_script(segment_count: int, filter_chains: str, concat_inputs: str, *, include_video: bool) -> str:
    """Build a complete ffmpeg concat filter graph."""
    if include_video:
        return f"{filter_chains}{concat_inputs}concat=n={segment_count}:v=1:a=1[outv][outa]"
    return f"{filter_chains}{concat_inputs}concat=n={segment_count}:v=0:a=1[outa]"


def build_audio_concat_filter_graph(segments_to_keep: list[tuple[float, float]]) -> str:
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


def build_video_audio_concat_filter_graph(segments_to_keep: list[tuple[float, float]]) -> str:
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


def build_video_lavfi_audio_concat_filter_graph(segments_to_keep: list[tuple[float, float]]) -> str:
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


def build_video_audio_concat_filter_graph_with_title_overlay(
    segments_to_keep: list[tuple[float, float]],
) -> str:
    """Build trim/concat graph and overlay a pre-rendered title PNG banner."""
    segment_count = len(segments_to_keep)
    filter_chains = "".join(
        (
            f"[0:v]trim=start={segment_start}:end={segment_end},setpts=PTS-STARTPTS[v{i}];"
            f"[0:a]atrim=start={segment_start}:end={segment_end},asetpts=PTS-STARTPTS[a{i}];"
        )
        for i, (segment_start, segment_end) in enumerate(segments_to_keep)
    )
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(segment_count))
    return (
        f"{filter_chains}{concat_inputs}concat=n={segment_count}:v=1:a=1[outv][outa];"
        "[1:v]format=rgba[overlay];"
        "[outv][overlay]overlay=0:0:shortest=1[outv]"
    )


def build_video_lavfi_audio_concat_filter_graph_with_title_overlay(
    segments_to_keep: list[tuple[float, float]],
) -> str:
    """Like `build_video_audio_concat_filter_graph_with_title_overlay` but audio from lavfi input 2."""
    segment_count = len(segments_to_keep)
    filter_chains = "".join(
        (
            f"[0:v]trim=start={segment_start}:end={segment_end},setpts=PTS-STARTPTS[v{i}];"
            f"[2:a]atrim=start=0:end={_segment_audio_duration_sec(segment_start, segment_end)},"
            f"asetpts=PTS-STARTPTS[a{i}];"
        )
        for i, (segment_start, segment_end) in enumerate(segments_to_keep)
    )
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(segment_count))
    return (
        f"{filter_chains}{concat_inputs}concat=n={segment_count}:v=1:a=1[outv][outa];"
        "[1:v]format=rgba[overlay];"
        "[outv][overlay]overlay=0:0:shortest=1[outv]"
    )
