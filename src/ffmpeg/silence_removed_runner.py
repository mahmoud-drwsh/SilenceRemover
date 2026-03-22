"""Shared FFmpeg orchestration for silence-removed encode paths (audio + video)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from src.core.constants import SCRIPTS_DIR
from src.core.fs_utils import wait_for_file_release
from src.ffmpeg.core import print_ffmpeg_cmd
from src.ffmpeg.filter_graph import write_filter_graph_script
from src.ffmpeg.runner import format_ffmpeg_process_failure, run, run_with_progress


def run_minimal_ffmpeg_output(
    *,
    output_file: Path,
    cmd: list[str],
    command_label: str,
) -> Path:
    print_ffmpeg_cmd(cmd)
    try:
        run(cmd, check=True)
        wait_for_file_release(output_file)
        return output_file.resolve()
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            format_ffmpeg_process_failure(command_label, exc)
        ) from exc


def run_silence_removed_media(
    *,
    input_file: Path,
    output_file: Path,
    temp_dir: Path,
    segments_to_keep: list[tuple[float, float]],
    build_filter_graph: Callable[[list[tuple[float, float]], int | None], str],
    build_command: Callable[[Path, Path, Path], list[str]],
    expected_total_seconds: Optional[float] = None,
    on_progress: Optional[Callable[[int], None]] = None,
    command_label: Optional[str] = None,
    overlay_y: int | None = None,
) -> Path:
    filter_complex = build_filter_graph(segments_to_keep, overlay_y)

    scripts_dir = temp_dir / SCRIPTS_DIR
    scripts_dir.mkdir(parents=True, exist_ok=True)
    filter_script_path = scripts_dir / f"{output_file.stem}_{int(time.time())}.ffscript"
    write_filter_graph_script(filter_script_path, filter_complex)

    cmd = build_command(input_file, output_file, filter_script_path)
    print_ffmpeg_cmd(cmd)
    if expected_total_seconds is not None:
        emitted_progress = False

        def _on_progress(percent: int) -> None:
            nonlocal emitted_progress
            emitted_progress = True
            if on_progress is not None:
                on_progress(percent)

        try:
            run_with_progress(
                cmd,
                expected_total_seconds=expected_total_seconds,
                on_progress=_on_progress,
            )
        except subprocess.CalledProcessError as exc:
            if command_label is None:
                raise
            raise RuntimeError(
                format_ffmpeg_process_failure(command_label, exc)
            ) from exc
        if emitted_progress:
            print()
    else:
        try:
            run(cmd, check=True)
        except subprocess.CalledProcessError as exc:
            if command_label is not None:
                raise RuntimeError(
                    format_ffmpeg_process_failure(command_label, exc)
                ) from exc
            raise

    wait_for_file_release(output_file)
    print(f"Done! Output saved to: {output_file}")
    return output_file.resolve()


__all__ = ["run_minimal_ffmpeg_output", "run_silence_removed_media"]
