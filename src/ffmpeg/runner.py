"""Subprocess execution helpers for FFmpeg/FFprobe workflows."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess

ProgressCallback = Callable[[int], None]


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


def parse_progress_seconds(line: str) -> float | None:
    """Parse FFmpeg -progress output into seconds."""
    if line.startswith("out_time_ms="):
        try:
            return float(line.split("=", 1)[1]) / 1_000_000.0
        except ValueError:
            return None
    if line.startswith("out_time="):
        value = line.split("=", 1)[1]
        try:
            hours, minutes, seconds = value.split(":")
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except (ValueError, TypeError):
            return None
    return None


def run_with_progress(
    cmd: list[str],
    *,
    expected_total_seconds: float,
    on_progress: ProgressCallback | None = None,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run FFmpeg and forward progress updates using -progress output."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
    )
    output_lines: list[str] = []
    stderr_lines: list[str] = []
    current_percent = -1
    try:
        if proc.stdout is None:
            raise RuntimeError("ffmpeg progress read failed: stdout pipe unavailable")
        for raw_line in proc.stdout:
            output_lines.append(raw_line)
            line = raw_line.strip()
            if not line:
                continue
            seconds = parse_progress_seconds(line)
            if seconds is None:
                continue
            if expected_total_seconds > 0:
                percent = int(min(100.0, max(0.0, (seconds / expected_total_seconds) * 100.0)))
                if percent != current_percent:
                    current_percent = percent
                    if on_progress is not None:
                        on_progress(percent)
    finally:
        return_code = proc.wait()
        if proc.stderr is not None:
            stderr_lines.append(proc.stderr.read())
    if check and return_code != 0:
        raise subprocess.CalledProcessError(
            return_code,
            cmd,
            output="".join(output_lines),
            stderr="".join(stderr_lines),
        )
    return subprocess.CompletedProcess(cmd, return_code, "".join(output_lines), "".join(stderr_lines))


def run_if_exists(path: Path, cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a command after ensuring a required output path parent exists.

    Currently this utility is intentionally narrow and only ensures the
    destination parent directory exists for filesystem safety.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    return run(cmd)
