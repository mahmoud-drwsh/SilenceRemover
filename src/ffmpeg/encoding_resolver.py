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
            "-preset", "3",
            "-q:v", "21",
            "-look_ahead_depth", "23",
            "-mbbrc", "1",
            "-extbrc", "1",
            "-scenario", "archive",
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


def _probe_encoder_profile(profile: VideoEncoderProfile) -> VideoEncoderProfile:
    """Verify an encoder profile by probing with exact encoder arguments."""
    if can_run_encoder(profile.codec, profile.codec_args):
        return profile

    raise RuntimeError(
        f"Encoder '{profile.name}' is not runnable with configured options: {list(profile.codec_args)}"
    )


def resolve_video_encoder() -> VideoEncoderProfile:
    """Resolve the first supported video encoder from the internal priority list."""
    global _RESOLVED_ENCODER
    if _RESOLVED_ENCODER is not None:
        return _RESOLVED_ENCODER

    available = _get_available_encoders()
    probe_failures: list[str] = []
    for profile in _ENCODER_PROFILES:
        if profile.codec not in available:
            continue
        try:
            probe_result = _probe_encoder_profile(profile)
            _RESOLVED_ENCODER = probe_result
            return probe_result
        except RuntimeError as exc:
            probe_failures.append(f"{profile.name}: {exc}")
            continue

    supported = ", ".join(sorted(profile.codec for profile in _ENCODER_PROFILES))
    if probe_failures:
        raise RuntimeError(
            f"Configured encoder profiles are not runnable. Tried in order: {supported}. "
            f"Probe failures: {'; '.join(probe_failures)}"
        )
    raise RuntimeError(
        f"No runnable hardware encoder found. Tried in order: {supported}. "
        "Install/configure one of these encoders in your ffmpeg build."
    )


__all__ = ["VideoEncoderProfile", "resolve_video_encoder"]
