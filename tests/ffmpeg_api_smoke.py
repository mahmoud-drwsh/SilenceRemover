"""Manual FFmpeg API smoke checks (no duplicate command logic)."""

from __future__ import annotations

from pathlib import Path

from src.ffmpeg.encoding_resolver import resolve_video_encoder
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

    cmd_min = build_minimal_video_command(
        input_file=Path("input.mp4"),
        output_file=Path("output-min.mp4"),
        encoder=profile,
    )
    if not cmd_min or cmd_min[-1] != "output-min.mp4":
        _fail("Minimal video command assembly returned an unexpected output path.")
    _ok("Minimal encode command assembly sanity passed.")

    print("Smoke test completed successfully.")


if __name__ == "__main__":
    main()
