"""FFmpeg probe helpers for media metadata and encoder capability checks."""

from __future__ import annotations

import json
import shlex
import unicodedata
from pathlib import Path
from typing import Sequence

from src.core.constants import (
    BITRATE_FALLBACK_BPS,
    FINAL_VIDEO_SOURCE_METADATA_KEY,
    LEGACY_FINAL_VIDEO_SOURCE_METADATA_KEY,
)
from src.ffmpeg.core import build_ffmpeg_cmd, build_ffprobe_cmd
from src.ffmpeg.runner import run
from sr_ffmpeg_cmd_builder import (
    build_encoder_probe_command,
    build_ffprobe_format_json_command,
    build_ffprobe_has_audio_command,
    build_ffprobe_metadata_command,
    build_ffprobe_stream_dimensions_command,
)
from sr_progress_formatter import parse_ffmpeg_encoder_lines


def get_available_encoders() -> set[str]:
    """Return supported encoder names from the current FFmpeg installation."""
    cmd = build_ffmpeg_cmd(False, "-encoders")
    result = run(cmd, check=True, capture_output=True)
    return parse_ffmpeg_encoder_lines(result.stdout)


def run_ffprobe_float(input_file: Path, format_entry: str, fallback: float) -> float:
    """Run ffprobe and parse a float metadata field."""
    result = run(build_ffprobe_metadata_command(input_file, format_entry), capture_output=True, check=False)
    output = result.stdout.strip()
    try:
        return float(output)
    except (TypeError, ValueError):
        return fallback


def probe_has_audio_stream(input_file: Path) -> bool:
    """True if ffprobe finds any audio stream on the file."""
    result = run(build_ffprobe_has_audio_command(input_file), capture_output=True, check=False)
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def probe_video_dimensions(input_file: Path) -> tuple[int, int]:
    """Probe and return (width, height) for the first video stream."""
    result = run(build_ffprobe_stream_dimensions_command(input_file), capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to probe dimensions for {input_file}") from None

    raw_dimensions = result.stdout.strip().replace(" ", "")
    if not raw_dimensions:
        raise RuntimeError(f"Failed to read dimensions for {input_file}")

    parts = [part for part in re.split(r"[, \n]", raw_dimensions) if part]
    if len(parts) < 2:
        raise RuntimeError(f"Unexpected ffprobe dimensions format for {input_file}: {result.stdout}")

    width = int(parts[0])
    height = int(parts[1])
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid dimensions for {input_file}: {width}x{height}")
    return width, height


def probe_ffmpeg_can_decode_image_frame(path: Path) -> None:
    """Raise ``RuntimeError`` if FFmpeg cannot decode at least one frame.

    Use for optional assets (e.g. logo PNG) where ffprobe dimensions can succeed
    while the PNG demuxer/decoder fails during encode (corrupt chunks, AV locks).
    """
    cmd = build_ffmpeg_cmd(True, "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "null", "-")
    result = run(cmd, capture_output=True, check=False)
    if result.returncode != 0:
        tail = (result.stderr or "").strip()
        if len(tail) > 400:
            tail = f"{tail[:400]}..."
        raise RuntimeError(tail or f"FFmpeg could not decode image: {path}")


def can_run_encoder(codec: str, codec_args: Sequence[str] = ()) -> bool:
    """Check whether the given codec can run in a minimal encode test."""
    cmd = build_encoder_probe_command(codec, codec_args)
    result = run(cmd, capture_output=True, check=False)
    if result.returncode != 0:
        quoted_cmd = " ".join(shlex.quote(arg) for arg in cmd)
        print(f"FFmpeg probe failed for codec={codec}:")
        print(f"  Command: {quoted_cmd}")
        print(f"  Return code: {result.returncode}")
        if result.stderr:
            print(f"  Stderr: {result.stderr.strip()}")
        return False
    return True


def probe_duration(input_file: Path) -> float:
    """Probe media duration in seconds."""
    return run_ffprobe_float(input_file, "duration", 0.0)


def read_format_tags(input_file: Path) -> dict[str, str]:
    """Return format-level tag dict from ffprobe JSON, or empty if missing."""
    result = run(build_ffprobe_format_json_command(input_file), capture_output=True, check=False)
    if result.returncode != 0:
        return {}
    try:
        raw = result.stdout
        if raw is None:
            return {}
        text_out = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
        data = json.loads(text_out)
    except json.JSONDecodeError:
        return {}
    tags = data.get("format", {}).get("tags") or {}
    if not isinstance(tags, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in tags.items():
        if isinstance(k, str):
            out[k] = v if isinstance(v, str) else str(v)
    return out


def _nfc(s: str) -> str:
    """Normalize for comparison (macOS paths often differ from muxed metadata in NFD vs NFC)."""
    return unicodedata.normalize("NFC", s.strip())


def _tag_matches_source(tags: dict[str, str], source_filename: str) -> bool:
    """Match `comment` or legacy key; keys may vary in casing; values vs Path.name need NFC match."""
    want = _nfc(source_filename)
    legacy = LEGACY_FINAL_VIDEO_SOURCE_METADATA_KEY
    for k, v in tags.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        key_l = k.lower()
        if key_l in (FINAL_VIDEO_SOURCE_METADATA_KEY.lower(), "comment"):
            if _nfc(v) == want:
                return True
        if k == legacy or key_l == legacy.lower():
            if _nfc(v) == want:
                return True
    return False


def delete_final_videos_matching_source(output_dir: Path, source_filename: str) -> int:
    """Remove output MP4s whose source tag equals source_filename.

    Used only from the title editor when a title is changed. The pipeline does not call this.
    Returns the number of files removed.
    """
    removed = 0
    out = output_dir.resolve()
    if not out.is_dir():
        return 0
    for mp4 in sorted(out.glob("*.mp4")):
        tags = read_format_tags(mp4)
        if _tag_matches_source(tags, source_filename):
            mp4.unlink(missing_ok=True)
            removed += 1
    return removed


def probe_bitrate_bps(input_file: Path, fallback: int = BITRATE_FALLBACK_BPS) -> int:
    """Probe format-level bitrate and return it in bits-per-second."""
    result = run_ffprobe_float(input_file, "bit_rate", float(fallback))
    if result == float(fallback):
        return fallback
    try:
        return int(result)
    except (TypeError, ValueError):
        return fallback
