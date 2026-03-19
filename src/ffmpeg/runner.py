"""Subprocess execution helpers for FFmpeg/FFprobe workflows."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess

ProgressCallback = Callable[[int], None]

_MODERN_FILTER_COMPLEX_FLAG = "-/filter_complex"
_LEGACY_FILTER_COMPLEX_FLAG = "-filter_complex_script"
_FILTER_COMPLEX_OPTION_MARKERS = (
    "unknown option",
    "unrecognized option",
    "not recognized",
    "no such option",
)


def _filter_complex_script_fallback_command(cmd: list[str]) -> list[str] | None:
    """Return a command copy that uses the legacy filter-complex-script flag."""
    if _MODERN_FILTER_COMPLEX_FLAG not in cmd:
        return None
    return [_LEGACY_FILTER_COMPLEX_FLAG if arg == _MODERN_FILTER_COMPLEX_FLAG else arg for arg in cmd]


def _normalize_stderr(stderr: object) -> str:
    """Normalize stderr output to lowercase text for robust matching."""
    if isinstance(stderr, bytes):
        return stderr.decode("utf-8", errors="replace").lower()
    if isinstance(stderr, str):
        return stderr.lower()
    return ""


def _is_filter_complex_option_error(stderr: object) -> bool:
    """Detect the FFmpeg error path when modern filter-complex option is unsupported."""
    error_text = _normalize_stderr(stderr)
    if "filter_complex" not in error_text:
        return False
    return any(marker in error_text for marker in _FILTER_COMPLEX_OPTION_MARKERS)


def run(
    cmd: list[str],
    *,
    check: bool = True,
    capture_output: bool = False,
    text: bool = True,
    **kwargs,
) -> subprocess.CompletedProcess[str]:
    """Run a command and optionally raise on non-zero exit."""
    has_modern_filter_flag = _MODERN_FILTER_COMPLEX_FLAG in cmd
    uses_custom_stdio = ("stdout" in kwargs) or ("stderr" in kwargs)
    # Preserve default behavior unless we need stderr for fallback detection.
    use_capture_output = capture_output or (has_modern_filter_flag and check and not uses_custom_stdio)
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=use_capture_output,
        text=text,
        **kwargs,
    )
    if has_modern_filter_flag and _is_filter_complex_option_error(result.stderr):
        fallback_cmd = _filter_complex_script_fallback_command(cmd)
        if fallback_cmd is not None:
            fallback_result = run(
                fallback_cmd,
                check=False,
                capture_output=use_capture_output,
                text=text,
                **kwargs,
            )
            if not check:
                return fallback_result
            if fallback_result.returncode == 0:
                return fallback_result
            if check:
                raise subprocess.CalledProcessError(
                    fallback_result.returncode,
                    fallback_cmd,
                    output=fallback_result.stdout,
                    stderr=fallback_result.stderr,
                )
            return fallback_result
        if check:
            raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
        return result
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
    has_modern_filter_flag = _MODERN_FILTER_COMPLEX_FLAG in cmd

    def _run(cmd_input: list[str]) -> subprocess.CompletedProcess[str]:
        proc = subprocess.Popen(
            cmd_input,
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
        stdout_text = "".join(output_lines)
        stderr_text = "".join(stderr_lines)
        return subprocess.CompletedProcess(cmd_input, return_code, stdout_text, stderr_text)

    result = _run(cmd)
    if has_modern_filter_flag and _is_filter_complex_option_error(result.stderr):
        fallback_cmd = _filter_complex_script_fallback_command(cmd)
        if fallback_cmd is not None:
            fallback_result = run_with_progress(
                fallback_cmd,
                expected_total_seconds=expected_total_seconds,
                on_progress=on_progress,
                check=check,
                text=text,
            )
            if fallback_result.returncode == 0 or not check:
                return fallback_result
            result = fallback_result
        if check:
            raise subprocess.CalledProcessError(
                result.returncode,
                cmd,
                output=result.stdout,
                stderr=result.stderr,
            )
        return result
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            cmd,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def run_if_exists(path: Path, cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a command after ensuring a required output path parent exists.

    Currently this utility is intentionally narrow and only ensures the
    destination parent directory exists for filesystem safety.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    return run(cmd)
