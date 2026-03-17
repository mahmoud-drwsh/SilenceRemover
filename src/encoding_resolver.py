"""Utilities for resolving the video encoder profile used by FFmpeg.

The resolver centralizes both codec selection and encoder-specific options so
adding additional hardware encoders in the future only requires updating this file.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from functools import lru_cache
import re


_RESOLVED_ENCODER: VideoEncoderProfile | None = None


def _parse_ffmpeg_encoder_lines(output: str) -> set[str]:
    """Extract encoder names from `ffmpeg -encoders` output."""
    encoders: set[str] = set()
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue

        match = _ENCODER_LINE_RE.match(raw_line)
        if match is None:
            continue

        parts = raw_line.split()
        encoder = parts[1]
        if encoder:
            encoders.add(encoder)
    return encoders


@dataclass(frozen=True)
class VideoEncoderProfile:
    """Resolved encoder configuration with codec and related FFmpeg args."""

    name: str
    codec: str
    codec_args: tuple[str, ...] = ()
    container_args: tuple[str, ...] = ()

    def video_args(self, *, include_container_args: bool = False) -> list[str]:
        args: list[str] = ["-c:v", self.codec]
        args.extend(self.codec_args)
        if include_container_args:
            args.extend(self.container_args)
        return args


_ENCODER_PROFILES: tuple[VideoEncoderProfile, ...] = (
    VideoEncoderProfile(
        name="intel_quick_sync_hevc",
        codec="hevc_qsv",
        codec_args=(
            "-preset",
            "slow",
            "-global_quality",
            "18",
            "-look_ahead_depth",
            "20",
            "-mbbrc",
            "1",
            "-extbrc",
            "1",
            "-scenario",
            "archive",
        ),
        container_args=("-tag:v", "hvc1", "-movflags", "+faststart"),
    ),
    VideoEncoderProfile(
        name="apple_videotoolbox_hevc",
        codec="hevc_videotoolbox",
        codec_args=(
            "-q:v",
            "32",            
        ),
        container_args=("-tag:v", "hvc1", "-movflags", "+faststart"),
    ),
)


_ENCODER_LINE_RE = re.compile(r"^\s*[.A-Z]{6}\s+\S+")


@lru_cache(maxsize=1)
def _get_available_encoders() -> set[str]:
    """Return supported FFmpeg encoder names from current installation."""
    completed = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=True,
    )
    return _parse_ffmpeg_encoder_lines(completed.stdout)


def _can_run_encoder(profile: VideoEncoderProfile) -> bool:
    """Verify an encoder profile actually runs with a minimal encode test."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=black:s=16x16:d=0.1",
        "-frames:v",
        "1",
        "-c:v",
        profile.codec,
    ]
    cmd.extend(profile.codec_args)
    cmd.extend(["-f", "null", "-"])
    return subprocess.run(cmd, capture_output=True, text=True).returncode == 0


def resolve_video_encoder() -> VideoEncoderProfile:
    """Resolve the first supported video encoder from the internal priority list."""
    global _RESOLVED_ENCODER
    if _RESOLVED_ENCODER is not None:
        return _RESOLVED_ENCODER

    available = _get_available_encoders()
    for profile in _ENCODER_PROFILES:
        if profile.codec not in available:
            continue
        if _can_run_encoder(profile):
            _RESOLVED_ENCODER = profile
            return profile

    supported = ", ".join(sorted(profile.codec for profile in _ENCODER_PROFILES))
    raise RuntimeError(
        f"No runnable hardware encoder found. Tried in order: {supported}. "
        "Install/configure one of these encoders in your ffmpeg build."
    )


__all__ = ["VideoEncoderProfile", "resolve_video_encoder"]
