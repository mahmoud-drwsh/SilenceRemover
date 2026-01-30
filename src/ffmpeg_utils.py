"""FFmpeg command building and hardware acceleration utilities."""

import shlex
import subprocess
from pathlib import Path


def print_ffmpeg_cmd(cmd: list[str]) -> None:
    """Print the ffmpeg command before execution so users can see what is being run."""
    if not cmd or cmd[0] != "ffmpeg":
        return
    # Print as a copy-pastable shell command (quote args with spaces)
    quoted = [shlex.quote(str(a)) for a in cmd]
    print("FFmpeg:", " ".join(quoted))


def build_ffmpeg_cmd(overwrite: bool = True, hwaccel: str | None = None, *additional_flags: str) -> list[str]:
    """Build a base FFmpeg command with common flags.
    
    Args:
        overwrite: If True, add -y flag to overwrite output files
        hwaccel: Optional hardware acceleration method name
        *additional_flags: Additional flags to append to the command
        
    Returns:
        List of command arguments starting with 'ffmpeg'
        
    Example:
        >>> cmd = build_ffmpeg_cmd(overwrite=True, hwaccel="videotoolbox")
        >>> cmd += ["-i", "input.mp4", "-c:v", "libx264", "output.mp4")
    """
    cmd = ["ffmpeg", "-hide_banner"]
    if overwrite:
        cmd.append("-y")
    if hwaccel:
        cmd.extend(["-hwaccel", hwaccel])
    cmd.extend(additional_flags)
    return cmd


def choose_hwaccel() -> str | None:
    """Choose the best available hardware acceleration method for FFmpeg.
    
    Returns:
        Hardware acceleration method name, or None if none available
    """
    try:
        cmd = build_ffmpeg_cmd(overwrite=False)
        cmd.append("-hwaccels")
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
    except Exception:
        return None
    preferred = ["videotoolbox", "cuda", "qsv", "d3d11va", "dxva2", "vaapi"]
    available = {line.strip() for line in out.splitlines() if line.strip() and not line.startswith("Hardware acceleration methods")}
    for hw in preferred:
        if hw in available:
            return hw
    return None
