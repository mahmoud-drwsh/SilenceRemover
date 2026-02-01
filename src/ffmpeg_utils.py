"""FFmpeg command building utilities."""

import shlex


def print_ffmpeg_cmd(cmd: list[str]) -> None:
    """Print the ffmpeg command before execution so users can see what is being run."""
    if not cmd or cmd[0] != "ffmpeg":
        return
    # Print as a copy-pastable shell command (quote args with spaces)
    quoted = [shlex.quote(str(a)) for a in cmd]
    print("FFmpeg:", " ".join(quoted))


def build_ffmpeg_cmd(overwrite: bool = True, *additional_flags: str) -> list[str]:
    """Build a base FFmpeg command with common flags.

    Args:
        overwrite: If True, add -y flag to overwrite output files
        *additional_flags: Additional flags to append to the command

    Returns:
        List of command arguments starting with 'ffmpeg'
    """
    cmd = ["ffmpeg", "-hide_banner", " -stats"]
    if overwrite:
        cmd.append("-y")
    cmd.extend(additional_flags)
    return cmd
