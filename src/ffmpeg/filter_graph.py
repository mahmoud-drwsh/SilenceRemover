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


def write_filter_graph_script(path: Path, filter_graph: str) -> Path:
    """Write filter graph text to a file and return the path."""
    path.write_text(filter_graph, encoding="utf-8")
    return path
