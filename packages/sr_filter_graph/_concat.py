"""Concat filter graph builders.

Pure functions that generate FFmpeg filter graph strings for audio/video concatenation.
"""

from sr_filter_graph._core import _segment_audio_duration_sec


def build_filter_graph_script(segment_count: int, filter_chains: str, concat_inputs: str, *, include_video: bool) -> str:
    """Build a complete ffmpeg concat filter graph.
    
    Args:
        segment_count: Number of segments to concatenate
        filter_chains: Filter chain definitions (trim operations)
        concat_inputs: Concatenated input labels (e.g., "[v0][a0][v1][a1]")
        include_video: Whether video stream is included
        
    Returns:
        Complete filter graph string for FFmpeg -filter_complex_script
    """
    if include_video:
        return f"{filter_chains}{concat_inputs}concat=n={segment_count}:v=1:a=1[outv][outa]"
    return f"{filter_chains}{concat_inputs}concat=n={segment_count}:v=0:a=1[outa]"


def build_audio_concat_filter_graph(
    segments_to_keep: list[tuple[float, float]],
    overlay_y: int | None = None,
) -> str:
    """Build audio-only concat graph from keep segments.
    
    Creates a filter graph that extracts and concatenates audio segments from input.
    
    Args:
        segments_to_keep: List of (start, end) timestamps in seconds
        overlay_y: Unused parameter for API compatibility
        
    Returns:
        FFmpeg filter graph string for audio-only concatenation
    """
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
    """Build video+audio concat graph from keep segments.
    
    Creates a filter graph that extracts and concatenates video and audio segments
    from the same input file.
    
    Args:
        segments_to_keep: List of (start, end) timestamps in seconds
        overlay_y: Unused parameter for API compatibility
        
    Returns:
        FFmpeg filter graph string for video+audio concatenation
    """
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


def build_video_lavfi_audio_concat_filter_graph(
    segments_to_keep: list[tuple[float, float]],
    overlay_y: int | None = None,
) -> str:
    """Build video from input 0 + silent stereo audio from lavfi input 1.
    
    Creates a filter graph for video-only inputs where audio is generated via lavfi.
    Each segment gets audio of matching duration from the lavfi source.
    
    Args:
        segments_to_keep: List of (start, end) timestamps in seconds
        overlay_y: Unused parameter for API compatibility
        
    Returns:
        FFmpeg filter graph string for video+lavfi audio concatenation
    """
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
