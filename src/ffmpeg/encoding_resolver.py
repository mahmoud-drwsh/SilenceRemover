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
        name="hevc_qsv_hardware_primary",
        codec="hevc_qsv",
        codec_args=(
            "-preset",
            "slow",
            "-global_quality",
            "20",
            "-extbrc",
            "1",
            "-look_ahead_depth",
            "20",
            "-adaptive_i",
            "1",
            "-adaptive_b",
            "1",
            "-forced_idr",
            "1",
            "-async_depth",
            "4",
        ),
        container_args=("-tag:v", "hvc1", "-movflags", "+faststart"),
    ),
    VideoEncoderProfile(
        name="libx265_software_hevc",
        codec="libx265",
        codec_args=(
            "-crf",
            "24",
            "-preset",
            "slow",
        ),
        container_args=("-tag:v", "hvc1", "-movflags", "+faststart"),
    ),
)


_LIBX265_VERIFY_HINT = (
    "Install a full FFmpeg build that includes encoder libx265 (often GPL-licensed). "
    "Check: ffmpeg -hide_banner -encoders (look for libx265)."
)
_HEVC_QSV_VERIFY_HINT = (
    "Ensure FFmpeg includes encoder hevc_qsv and Intel Quick Sync runtime support. "
    "Check: ffmpeg -hide_banner -encoders (look for hevc_qsv)."
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
    """Resolve final video encoder with hevc_qsv primary and libx265 fallback."""
    global _RESOLVED_ENCODER
    if _RESOLVED_ENCODER is not None:
        return _RESOLVED_ENCODER

    available = _get_available_encoders()
    qsv_profile, libx265_profile = _ENCODER_PROFILES

    # Try primary encoder (hevc_qsv) first
    if qsv_profile.codec in available:
        try:
            _RESOLVED_ENCODER = _probe_encoder_profile(qsv_profile)
            return _RESOLVED_ENCODER
        except RuntimeError:
            # QSV probe failed - hardware not available or drivers missing
            # Fall through to try software encoder
            pass

    # Try fallback encoder (libx265)
    if libx265_profile.codec not in available:
        raise RuntimeError(
            f"FFmpeg does not list fallback encoder '{libx265_profile.codec}'. {_LIBX265_VERIFY_HINT}"
        )

    try:
        _RESOLVED_ENCODER = _probe_encoder_profile(libx265_profile)
    except RuntimeError as exc:
        raise RuntimeError(
            f"Fallback encoder '{libx265_profile.codec}' is listed but a probe encode failed. {_LIBX265_VERIFY_HINT}"
        ) from exc

    return _RESOLVED_ENCODER


__all__ = ["VideoEncoderProfile", "resolve_video_encoder"]
