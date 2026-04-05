"""Manual FFmpeg API smoke checks (no duplicate command logic)."""

from __future__ import annotations

import sys
from pathlib import Path

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

from src.ffmpeg.core import build_qsv_hwaccel_flags
from src.ffmpeg.encoding_resolver import resolve_video_encoder
from sr_filter_graph import (
    build_minimal_encode_overlay_filter_complex,
    build_video_audio_concat_filter_graph_with_title_overlay,
)
from src.ffmpeg.probing import can_run_encoder, get_available_encoders
from src.ffmpeg.transcode import build_final_trim_command, build_minimal_video_command


def _ok(message: str) -> None:
    print(f"[OK] {message}")


def _warn(message: str) -> None:
    print(f"[WARN] {message}")


def _fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def main() -> None:
    print("== FFmpeg API smoke test ==")

    encoders = get_available_encoders()
    if not encoders:
        _fail("No encoders returned by ffmpeg -encoders.")
    _ok(f"Discovered {len(encoders)} encoders.")

    has_qsv = "hevc_qsv" in encoders
    has_x265 = "libx265" in encoders
    _ok(f"hevc_qsv listed: {has_qsv}")
    _ok(f"libx265 listed: {has_x265}")

    profile = resolve_video_encoder()
    _ok(f"Resolved encoder: {profile.name} ({profile.codec})")

    if has_qsv and profile.codec != "hevc_qsv":
        _fail("Expected hevc_qsv to be selected when listed.")
    if (not has_qsv) and profile.codec != "libx265":
        _fail("Expected libx265 fallback when hevc_qsv is absent.")

    if not can_run_encoder(profile.codec, profile.codec_args):
        _fail(f"Probe encode failed for resolved codec {profile.codec}.")
    _ok("Probe encode passed for resolved encoder profile.")

    if has_x265 and not can_run_encoder("libx265", ("-crf", "24", "-preset", "slow")):
        _warn("libx265 is listed but a direct probe with fallback args failed.")

    # Command-builder sanity via APIs only (no hand-built ffmpeg command strings).
    cmd_final = build_final_trim_command(
        input_file=Path("input.mp4"),
        output_file=Path("output.mp4"),
        filter_script_path=Path("output/temp/scripts/test.ffscript"),
        encoder=profile,
    )
    if not cmd_final or cmd_final[-1] != "output.mp4":
        _fail("Final trim command assembly returned an unexpected output path.")
    _ok("Final trim command assembly sanity passed.")

    if profile.codec == "hevc_qsv":
        cmd_final_qsv = build_final_trim_command(
            input_file=Path("input.mp4"),
            output_file=Path("output-qsv.mp4"),
            filter_script_path=Path("output/temp/scripts/test-qsv.ffscript"),
            encoder=profile,
            use_qsv_hardware_path=True,
        )
        hw_flags = build_qsv_hwaccel_flags()
        if not all(flag in cmd_final_qsv for flag in hw_flags):
            _fail("QSV final command is missing one or more hardware-path flags.")
        _ok("QSV final command includes hardware-path flags.")

    cmd_min = build_minimal_video_command(
        input_file=Path("input.mp4"),
        output_file=Path("output-min.mp4"),
        encoder=profile,
    )
    if not cmd_min or cmd_min[-1] != "output-min.mp4":
        _fail("Minimal video command assembly returned an unexpected output path.")
    _ok("Minimal encode command assembly sanity passed.")

    if profile.codec == "hevc_qsv":
        cmd_min_qsv = build_minimal_video_command(
            input_file=Path("input.mp4"),
            output_file=Path("output-min-qsv.mp4"),
            encoder=profile,
            use_qsv_hardware_path=True,
        )
        hw_flags = build_qsv_hwaccel_flags()
        if not all(flag in cmd_min_qsv for flag in hw_flags):
            _fail("QSV minimal command is missing one or more hardware-path flags.")
        _ok("QSV minimal command includes hardware-path flags.")

    overlay_fc = build_video_audio_concat_filter_graph_with_title_overlay(
        segments_to_keep=[(0.0, 1.0)],
        overlay_y=10,
        logo_enabled=True,
    )
    if "format=nv12[outv]" not in overlay_fc:
        _fail("Overlay concat filter graph is missing final nv12 normalization.")
    if "scale=" in overlay_fc:
        _fail("Overlay concat filter graph should not include runtime logo scaling.")
    _ok("Overlay concat filter graph includes final nv12 normalization.")

    minimal_overlay_fc = build_minimal_encode_overlay_filter_complex(
        title_overlay_y=10,
        logo_enabled=True,
    )
    if "format=nv12[outv]" not in minimal_overlay_fc:
        _fail("Minimal overlay filter graph is missing final nv12 normalization.")
    if "scale=" in minimal_overlay_fc:
        _fail("Minimal overlay filter graph should not include runtime logo scaling.")
    _ok("Minimal overlay filter graph includes final nv12 normalization.")

    print("Smoke test completed successfully.")


if __name__ == "__main__":
    main()
