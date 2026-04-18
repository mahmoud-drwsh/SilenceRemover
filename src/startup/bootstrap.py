"""Pipeline startup bootstrap and shared runtime initialization."""

from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path

from src.core.cli import collect_video_files, fail, require_input_dir, require_tools
from src.core.config import get_config, load_config
from src.core.constants import TITLE_FONT_DEFAULT, resolve_trim_defaults
from src.core.paths import create_temp_subdirs, sibling_dir



@dataclass(frozen=True)
class StartupContext:
    """Resolved startup state needed for the processing pipeline."""

    input_dir: Path
    output_dir: Path
    temp_dir: Path
    videos: list[Path]
    noise_threshold: float
    min_duration: float
    pad_sec: float
    target_length: float | None
    api_key: str
    title_font: str

    enable_title_overlay: bool
    enable_logo_overlay: bool


def build_startup_context(args: Namespace) -> StartupContext:
    """Build startup context after validating external dependencies and config."""
    input_dir = Path(args.input_dir)

    require_tools("ffmpeg", "ffprobe")
    require_input_dir(input_dir)

    try:
        load_config()
    except ValueError as exc:
        fail(str(exc))

    output_dir = sibling_dir(input_dir, "output")
    temp_dir = output_dir / "temp"
    create_temp_subdirs(temp_dir)

    trim_defaults = resolve_trim_defaults(
        target_length=args.target_length,
        noise_threshold=args.noise_threshold,
        min_duration=args.min_duration,
        pad_sec=getattr(args, "pad_sec", None),
    )

    pad_sec = trim_defaults.pad_sec
    api_key = get_config()["OPENROUTER_API_KEY"]
    videos = collect_video_files(input_dir)
    if not videos:
        fail(f"No video files found in '{input_dir}'")

    return StartupContext(
        input_dir=input_dir,
        output_dir=output_dir,
        temp_dir=temp_dir,
        videos=videos,
        noise_threshold=trim_defaults.noise_threshold,
        min_duration=trim_defaults.min_duration,
        pad_sec=pad_sec,
        target_length=args.target_length,
        api_key=api_key,
        title_font=(args.title_font or "").strip() or TITLE_FONT_DEFAULT,
        enable_title_overlay=getattr(args, "enable_title_overlay", False),
        enable_logo_overlay=getattr(args, "enable_logo_overlay", False),
    )
