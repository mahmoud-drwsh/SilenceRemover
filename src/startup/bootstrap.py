"""Pipeline startup bootstrap and shared runtime initialization."""

from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path

from src.core.cli import fail, require_input_dir, require_tools, require_videos_in
from src.core.config import get_config, load_config
from src.core.constants import (
    DEFAULT_MIN_DURATION,
    DEFAULT_NOISE_THRESHOLD,
    DEFAULT_PAD_SEC,
    VIDEO_EXTENSIONS,
    SIMPLE_DB,
    SIMPLE_MIN_DURATION,
)
from src.core.paths import create_temp_subdirs, sibling_dir
from src.ffmpeg.encoding_resolver import VideoEncoderProfile, resolve_video_encoder


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
    encoder: VideoEncoderProfile


def build_startup_context(args: Namespace) -> StartupContext:
    """Build startup context after validating external dependencies and config."""
    input_dir = Path(args.input_dir)

    require_tools("ffmpeg", "ffprobe")
    require_input_dir(input_dir)
    require_videos_in(input_dir)

    try:
        load_config()
    except ValueError as exc:
        fail(str(exc))

    try:
        selected_encoder = resolve_video_encoder()
    except RuntimeError as exc:
        fail(str(exc))

    output_dir = sibling_dir(input_dir, "output")
    temp_dir = output_dir / "temp"
    create_temp_subdirs(temp_dir)

    if args.noise_threshold is not None:
        noise_threshold = args.noise_threshold
    elif args.target_length is not None:
        noise_threshold = SIMPLE_DB
    else:
        noise_threshold = DEFAULT_NOISE_THRESHOLD

    if args.min_duration is not None:
        min_duration = args.min_duration
    elif args.target_length is not None:
        min_duration = SIMPLE_MIN_DURATION
    else:
        min_duration = DEFAULT_MIN_DURATION

    pad_sec = DEFAULT_PAD_SEC
    api_key = get_config()["OPENROUTER_API_KEY"]
    videos = sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)

    return StartupContext(
        input_dir=input_dir,
        output_dir=output_dir,
        temp_dir=temp_dir,
        videos=videos,
        noise_threshold=noise_threshold,
        min_duration=min_duration,
        pad_sec=pad_sec,
        target_length=args.target_length,
        api_key=api_key,
        encoder=selected_encoder,
    )
