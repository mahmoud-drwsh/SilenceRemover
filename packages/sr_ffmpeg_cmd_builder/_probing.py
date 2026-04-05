"""FFprobe command building utilities.

Pure functions that construct FFprobe command arrays for media probing.
No subprocess calls, no file I/O - just command assembly.
"""

from pathlib import Path


def build_ffprobe_metadata_command(input_file: Path, format_entry: str) -> list[str]:
    """Build a simple ffprobe format field query command.
    
    Args:
        input_file: Path to the media file to probe
        format_entry: The format field to query (e.g., "duration", "bit_rate")
        
    Returns:
        List of command arguments for ffprobe
        
    Example:
        >>> build_ffprobe_metadata_command(Path("video.mp4"), "duration")
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', ...]
    """
    return [
        "ffprobe",
        "-v", "error",
        "-show_entries", f"format={format_entry}",
        "-of", "default=nw=1:nk=1",
        str(input_file),
    ]


def build_ffprobe_stream_dimensions_command(input_file: Path) -> list[str]:
    """Build a command to query video stream width and height.
    
    Args:
        input_file: Path to the media file to probe
        
    Returns:
        List of command arguments for ffprobe
        
    Example:
        >>> build_ffprobe_stream_dimensions_command(Path("video.mp4"))
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', ...]
    """
    return [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0:nk=1",
        str(input_file),
    ]


def build_ffprobe_has_audio_command(input_file: Path) -> list[str]:
    """Build a command to check if file has audio streams.
    
    Args:
        input_file: Path to the media file to probe
        
    Returns:
        List of command arguments for ffprobe
        
    Example:
        >>> build_ffprobe_has_audio_command(Path("video.mp4"))
        ['ffprobe', '-v', 'error', '-select_streams', 'a', ...]
    """
    return [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        str(input_file),
    ]


def build_ffprobe_format_json_command(input_file: Path) -> list[str]:
    """Build a command to get format metadata as JSON.
    
    Args:
        input_file: Path to the media file to probe
        
    Returns:
        List of command arguments for ffprobe
        
    Example:
        >>> build_ffprobe_format_json_command(Path("video.mp4"))
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', ...]
    """
    return [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(input_file),
    ]
