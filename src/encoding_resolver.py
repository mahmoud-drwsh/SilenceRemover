"""Utilities for resolving the video encoder profile used by FFmpeg."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from src.ffmpeg.probing import can_run_encoder, get_available_encoders


_RESOLVED_ENCODER: VideoEncoderProfile | None = None


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


@lru_cache(maxsize=1)
def _get_available_encoders() -> set[str]:
    """Return supported FFmpeg encoder names from current installation."""
    return get_available_encoders()


def _can_run_encoder(profile: VideoEncoderProfile) -> bool:
    """Verify an encoder profile actually runs with a minimal encode test."""
    return can_run_encoder(profile.codec, profile.codec_args)


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
