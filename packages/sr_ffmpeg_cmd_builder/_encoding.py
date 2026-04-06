"""FFmpeg command building utilities.

Pure functions that construct FFmpeg command arrays for encoding and probing.
No subprocess calls, no file I/O - just command assembly.
"""

from typing import Sequence


def build_encoder_probe_command(codec: str, codec_args: Sequence[str] = ()) -> list[str]:
    """Build a probe command for testing encoder availability.
    
    Creates a command that encodes a short test video using the specified
    codec to verify FFmpeg can use it.
    
    Args:
        codec: The video codec to test (e.g., "libx264", "hevc_qsv")
        codec_args: Additional codec-specific arguments
        
    Returns:
        List of command arguments for ffmpeg
        
    Example:
        >>> build_encoder_probe_command("libx264")
        ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=duration=1:size=320x240', ...]
    """
    cmd = [
        "ffmpeg",
        "-v", "error",
        "-f", "lavfi",
        "-i", "testsrc=duration=1:size=320x240",  # Use testsrc - more compatible with HW encoders
        "-frames:v", "25",
        "-c:v", codec,
        "-pix_fmt", "yuv420p",
    ]
    cmd.extend(codec_args)
    cmd.extend(["-f", "null", "-"])
    return cmd
