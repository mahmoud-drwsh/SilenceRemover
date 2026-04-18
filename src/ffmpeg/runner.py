"""Subprocess execution helpers for FFmpeg/FFprobe workflows."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess
import sys

from sr_progress_formatter import parse_progress_seconds

ProgressCallback = Callable[[int, float], None]


def format_ffmpeg_process_failure(
    label: str,
    exc: subprocess.CalledProcessError,
) -> str:
    """Short failure label; FFmpeg details are expected on the process stderr stream (terminal)."""
    return f"{label} failed (exit {exc.returncode}). See FFmpeg output above on stderr."


def run(
    cmd: list[str],
    *,
    check: bool = True,
    capture_output: bool = False,
    text: bool = True,
    **kwargs,
) -> subprocess.CompletedProcess[str]:
    """Run a command and optionally raise on non-zero exit."""
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=capture_output,
        text=text,
        **kwargs,
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
    return result


def run_with_progress(
    cmd: list[str],
    *,
    expected_total_seconds: float,
    on_progress: ProgressCallback | None = None,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run FFmpeg and show the latest speed token from -progress on stdout.

    Stderr is inherited so FFmpeg logs and errors still go straight to the terminal.
    """
    stream = sys.stdout
    is_tty = bool(getattr(stream, "isatty", lambda: False)())
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=None,
        text=text,
    )
    output_lines: list[str] = []
    saw_speed = False
    current_percent = -1
    last_encoded_sec_int = -1
    try:
        if proc.stdout is None:
            raise RuntimeError("ffmpeg progress read failed: stdout pipe unavailable")
        for raw_line in proc.stdout:
            output_lines.append(raw_line)
            line = raw_line.strip()
            if not line:
                continue
            speed = _parse_ffmpeg_progress_speed(line)
            if speed is not None:
                clear_suffix = "\033[K" if is_tty else ""
                print(f"\r{speed}{clear_suffix}", end="", file=stream, flush=True)
                saw_speed = True

            seconds = parse_progress_seconds(line)
            if seconds is None or expected_total_seconds <= 0:
                continue

            percent = int(min(100.0, max(0.0, (seconds / expected_total_seconds) * 100.0)))
            encoded_sec_int = int(seconds)
            if percent != current_percent or encoded_sec_int != last_encoded_sec_int:
                current_percent = percent
                last_encoded_sec_int = encoded_sec_int
                if on_progress is not None:
                    on_progress(percent, seconds)
    finally:
        return_code = proc.wait()
        if saw_speed or return_code != 0:
            print(file=stream, flush=True)
    stdout_text = "".join(output_lines)
    result = subprocess.CompletedProcess(cmd, return_code, stdout_text, None)
    if check and return_code != 0:
        raise subprocess.CalledProcessError(return_code, cmd, output=stdout_text, stderr=None)
    return result


def run_if_exists(path: Path, cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a command after ensuring a required output path parent exists.

    Currently this utility is intentionally narrow and only ensures the
    destination parent directory exists for filesystem safety.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    return run(cmd)


def _parse_ffmpeg_progress_speed(line: str) -> str | None:
    """Return the speed token from an FFmpeg progress line."""
    if not line.startswith("speed="):
        return None
    speed = line.split("=", 1)[1].strip()
    if not speed or speed == "N/A":
        return None
    return speed
