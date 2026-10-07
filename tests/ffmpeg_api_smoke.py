"""Manual FFmpeg API smoke checks (no duplicate command logic)."""

from __future__ import annotations

import sys
from pathlib import Path

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

from src.ffmpeg.core import build_qsv_hwaccel_flags
from src.ffmpeg.encoding_resolver import get_encoder_config
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

    x265_config = get_encoder_config("X265")
    _ok(f"X265 config: codec={x265_config['codec']}, args={x265_config['args']}")

    if not can_run_encoder("libx265", x265_config["args"]):
        _fail(f"Probe encode failed for libx265 with config args.")
    _ok("Probe encode passed for libx265.")

    if has_x265 and not can_run_encoder("libx265", ("-crf", "24", "-preset", "slow")):
        _warn("libx265 is listed but a direct probe with fallback args failed.")

    cmd_final = build_final_trim_command(
        input_file=Path("input.mp4"),
        output_file=Path("output.mp4"),
        filter_script_path=Path("output/temp/scripts/test.ffscript"),
        encoder=x265_config["codec"],
    )
    if not cmd_final or cmd_final[-1] != "output.mp4":
        _fail("Final trim command assembly returned an unexpected output path.")
    _ok("Final trim command assembly sanity passed.")

    cmd_min = build_minimal_video_command(
        input_file=Path("input.mp4"),
        output_file=Path("output-min.mp4"),
        encoder=x265_config["codec"],
    )
    if not cmd_min or cmd_min[-1] != "output-min.mp4":
        _fail("Minimal video command assembly returned an unexpected output path.")
    _ok("Minimal encode command assembly sanity passed.")

    if has_qsv:
        qsv_config = get_encoder_config("QSV")
        cmd_final_qsv = build_final_trim_command(
            input_file=Path("input.mp4"),
            output_file=Path("output-qsv.mp4"),
            filter_script_path=Path("output/temp/scripts/test-qsv.ffscript"),
            encoder=qsv_config["codec"],
            use_qsv_hardware_path=True,
        )
        hw_flags = build_qsv_hwaccel_flags()
        if not all(flag in cmd_final_qsv for flag in hw_flags):
            _fail("QSV final command is missing one or more hardware-path flags.")
        _ok("QSV final command includes hardware-path flags.")

        cmd_min_qsv = build_minimal_video_command(
            input_file=Path("input.mp4"),
            output_file=Path("output-min-qsv.mp4"),
            encoder=qsv_config["codec"],
            use_qsv_hardware_path=True,
        )
        hw_flags = build_qsv_hwaccel_flags()
        if not all(flag in cmd_min_qsv for flag in hw_flags):
            _fail("QSV minimal command is missing one or more hardware-path flags.")
        _ok("QSV minimal command includes hardware-path flags.")

    print("Smoke test completed successfully.")


if __name__ == "__main__":
    main()
