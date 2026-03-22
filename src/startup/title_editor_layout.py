"""Layout paths for the standalone title editor (no OpenRouter / pipeline)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.core.cli import collect_video_files, fail, require_input_dir, require_tools
from src.core.paths import create_temp_subdirs, sibling_dir


@dataclass(frozen=True)
class TitleEditorLayout:
    """Paths needed to edit titles and scan output for source-tagged MP4s."""

    input_dir: Path
    output_dir: Path
    temp_dir: Path


def build_title_editor_layout(input_dir: Path) -> TitleEditorLayout:
    """Validate dirs and ffprobe; ensure output/temp exist. Requires at least one video."""
    require_tools("ffmpeg", "ffprobe")
    require_input_dir(input_dir)
    videos = collect_video_files(input_dir)
    if not videos:
        fail(f"No video files found in '{input_dir}'")
    output_dir = sibling_dir(input_dir, "output")
    temp_dir = output_dir / "temp"
    create_temp_subdirs(temp_dir)
    return TitleEditorLayout(
        input_dir=input_dir.resolve(),
        output_dir=output_dir.resolve(),
        temp_dir=temp_dir.resolve(),
    )
