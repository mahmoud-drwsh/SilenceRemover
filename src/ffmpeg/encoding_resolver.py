"""Utilities for resolving the video encoder profile used by FFmpeg."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from src.ffmpeg.probing import can_run_encoder, get_available_encoders


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
            "medium",
            "-global_quality",
            "19",  # ~5% quality increase over 20
            "-g",
            "250",  # 8+ second GOP for better compression (talking heads safe)
        ),
        container_args=("-tag:v", "hvc1", "-movflags", "+faststart"),
    ),
    VideoEncoderProfile(
        name="hevc_amf_hardware",
        codec="hevc_amf",
        codec_args=(
            "-rc",
            "qvbr",  # Quality VBR - scene-adaptive like QSV ICQ
            "-qvbr_quality_level",
            "18",  # ~20% quality increase over 22 (lower=better, range 0-51)
            "-g",
            "250",  # Longer GOP for better compression
        ),
        container_args=("-tag:v", "hvc1", "-movflags", "+faststart"),
    ),
    VideoEncoderProfile(
        name="libx265_software_hevc",
        codec="libx265",
        codec_args=(
            "-crf",
            "30",  # ~100MB for 3min talking heads
            "-preset",
            "medium",  # faster than slow, still efficient
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
_HEVC_AMF_VERIFY_HINT = (
    "Ensure FFmpeg includes encoder hevc_amf and AMD GPU drivers are installed. "
    "Check: ffmpeg -hide_banner -encoders (look for hevc_amf)."
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


def get_encoder_config(encoder_name: str) -> dict:
    """Get encoder configuration for explicit encoder choice.
    
    Args:
        encoder_name: One of "QSV", "AMF", "X265"
        
    Returns:
        Dict with codec, args, hwaccel flag
    """
    encoder_upper = encoder_name.upper()
    
    if encoder_upper == "QSV":
        return {
            "codec": "hevc_qsv",
            "args": ["-global_quality", "20", "-preset", "slow"],
            "hwaccel": True,
        }
    elif encoder_upper == "AMF":
        return {
            "codec": "hevc_amf", 
            "args": ["-qp_i", "22", "-qp_p", "22", "-quality", "quality"],
            "hwaccel": True,
        }
    else:
        return {
            "codec": "libx265",
            "args": ["-crf", "24", "-preset", "slow"],
            "hwaccel": False,
        }


__all__ = ["VideoEncoderProfile", "get_encoder_config"]
