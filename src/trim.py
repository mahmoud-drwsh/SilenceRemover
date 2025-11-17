"""Video trimming functionality."""

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from src.fs_utils import wait_for_file_release
from src.main_utils import (
    AUDIO_BITRATE,
    BITRATE_FALLBACK_BPS,
    PREFERRED_VIDEO_ENCODERS,
    build_ffmpeg_cmd,
    calculate_resulting_length,
    detect_silence_points,
    find_optimal_padding,
)

# Debug flag (set from CLI)
DEBUG = False


def _probe_duration(input_file: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(input_file)],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return float(out) if out else 0.0


def _probe_bitrate_bps(input_file: Path) -> int:
    format_probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=bit_rate", "-of", "default=nw=1:nk=1", str(input_file)],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return int(format_probe) if format_probe else BITRATE_FALLBACK_BPS


def _choose_video_encoder() -> str:
    cmd = build_ffmpeg_cmd(overwrite=False)
    cmd.append("-encoders")
    available_encoders = subprocess.run(cmd, capture_output=True, text=True).stdout
    return next((c for c in PREFERRED_VIDEO_ENCODERS if c in available_encoders), "libx264")


def trim_single_video(input_file: Path, output_dir: Path, noise_threshold: float, min_duration: float, pad_sec: float, target_length: Optional[float], debug: bool = False) -> Path:
    """Trim a single video and return the output file path."""
    global DEBUG
    DEBUG = debug
    
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = input_file.stem
    extension = input_file.suffix or ".mp4"
    output_file = (output_dir / f"{basename}{extension}").resolve()

    silence_starts, silence_ends = detect_silence_points(input_file, noise_threshold, min_duration, debug=DEBUG)
    duration_sec = _probe_duration(input_file)
    if duration_sec <= 0:
        raise ValueError(f"Invalid video duration: {duration_sec}s. Video file may be corrupted or empty.")
    if len(silence_starts) > len(silence_ends):
        silence_ends.append(duration_sec)

    if target_length is not None:
        if target_length >= duration_sec:
            # Target length is greater than or equal to original, skip trimming
            print(f"Target length ({target_length}s) >= original duration ({duration_sec:.3f}s), copying original file")
            try:
                import shutil
                shutil.copyfile(input_file, output_file)
                wait_for_file_release(output_file)
                print(f"Done! Output saved to: {output_file}")
                return output_file.resolve()
            except Exception as e:
                print(f"Error copying file: {e}", file=sys.stderr)
                raise
        optimal_pad = find_optimal_padding(silence_starts, silence_ends, duration_sec, target_length)
        pad_sec = optimal_pad
        resulting_length = calculate_resulting_length(silence_starts, silence_ends, duration_sec, pad_sec)
        print(f"Target length: {target_length}s")
        print(f"Calculated optimal padding: {pad_sec}s")
        print(f"Expected resulting length: {resulting_length:.3f}s")
        if resulting_length > target_length:
            print(f"Warning: Resulting length ({resulting_length:.3f}s) exceeds target ({target_length}s)")
        elif resulting_length < target_length:
            diff = target_length - resulting_length
            print(f"Note: Resulting length ({resulting_length:.3f}s) is {diff:.3f}s below target ({target_length}s)")

    segments_to_keep: list[tuple[float, float]] = []
    prev_end = 0.0
    for silence_start, silence_end in zip(silence_starts, silence_ends):
        if silence_end - silence_start <= pad_sec * 2:
            if DEBUG:
                print(f"[debug] skip silence ({silence_start:.3f}-{silence_end:.3f}) duration {silence_end - silence_start:.3f} <= {pad_sec*2:.3f}")
            continue
        if silence_start > prev_end:
            seg = (round(prev_end, 3), round(silence_start, 3))
            segments_to_keep.append(seg)
            if DEBUG:
                print(f"[debug] add segment keep={seg} from prev_end={prev_end:.3f} to silence_start={silence_start:.3f}")
        else:
            if DEBUG:
                print(f"[debug] no gap before silence_start={silence_start:.3f} (prev_end={prev_end:.3f}), merging")
        prev_end = max(0.0, silence_end - pad_sec)
        if DEBUG:
            print(f"[debug] set prev_end -> {prev_end:.3f} (silence_end={silence_end:.3f} pad={pad_sec:.3f})")
    if prev_end < duration_sec:
        segments_to_keep.append((round(prev_end, 3), round(duration_sec, 3)))
    if DEBUG:
        print(f"[debug] final segment from prev_end to end: {(round(prev_end, 3), round(duration_sec, 3))}")
        print(f"[debug] total segments_to_keep={len(segments_to_keep)} sample={segments_to_keep[:5]}")

    # Handle case where all audio is silence (no segments to keep)
    if len(segments_to_keep) == 0:
        print("Warning: All audio detected as silence. Creating minimal video (first frame only).")
        # Create minimal video with first frame and silence
        cmd = build_ffmpeg_cmd(overwrite=True)
        cmd.extend([
            "-i", str(input_file),
            "-t", "0.1",  # Very short duration
            "-c:v", "libx264",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE,
            str(output_file),
        ])
        subprocess.run(cmd, check=True)
        wait_for_file_release(output_file)
        print(f"Done! Output saved to: {output_file}")
        return output_file.resolve()

    filter_chains = ''.join(
        (
            f"[0:v]trim=start={segment_start}:end={segment_end},setpts=PTS-STARTPTS[v{segment_index}];"
            f"[0:a]atrim=start={segment_start}:end={segment_end},asetpts=PTS-STARTPTS[a{segment_index}];"
        )
        for segment_index, (segment_start, segment_end) in enumerate(segments_to_keep)
    )
    concat_inputs = ''.join(f"[v{i}][a{i}]" for i in range(len(segments_to_keep)))
    filter_complex = f"{filter_chains}{concat_inputs}concat=n={len(segments_to_keep)}:v=1:a=1[outv][outa]"

    video_codec = _choose_video_encoder()
    bitrate_bps = _probe_bitrate_bps(input_file)

    # On Windows the command-line length can be exceeded with very large filter graphs.
    # Use a temporary filter script to avoid hitting CreateProcess limits.
    filter_script_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".ffscript", delete=False, encoding="utf-8") as tf:
            tf.write(filter_complex)
            filter_script_path = tf.name

        # Use filter script to avoid long command lines (Windows) and keep compatibility.
        # Some FFmpeg builds may warn it's deprecated but still support it.
        cmd = build_ffmpeg_cmd(overwrite=True)
        cmd.extend([
            "-i", str(input_file),
            "-filter_complex_script", filter_script_path,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", video_codec, "-b:v", str(bitrate_bps),
            "-c:a", "aac", "-b:a", AUDIO_BITRATE, str(output_file),
        ])
    except Exception:
        # Fallback to inline filter if script creation fails
        cmd = build_ffmpeg_cmd(overwrite=True)
        cmd.extend([
            "-i", str(input_file),
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", video_codec, "-b:v", str(bitrate_bps),
            "-c:a", "aac", "-b:a", AUDIO_BITRATE, str(output_file),
        ])

    print(f"Input: {input_file}")
    print(f"Output: {output_file}")
    print(f"Settings: noise={noise_threshold}dB, min_duration={min_duration}s, pad={pad_sec}s")
    print(f"Filter complex length: {len(filter_complex)} characters")
    print(f"Number of segments: {len(segments_to_keep)}")
    print("Running FFmpeg command...")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        if video_codec != "libx264":
            print(f"Hardware encoder '{video_codec}' failed, retrying with software encoder 'libx264'...")
            cmd_fallback = cmd[:]
            try:
                idx = cmd_fallback.index("-c:v")
                cmd_fallback[idx + 1] = "libx264"
            except ValueError:
                cmd_fallback += ["-c:v", "libx264"]
            subprocess.run(cmd_fallback, check=True)
        else:
            raise
    finally:
        if filter_script_path:
            try:
                Path(filter_script_path).unlink(missing_ok=True)
            except Exception:
                pass
    
    wait_for_file_release(output_file)
    
    print(f"Done! Output saved to: {output_file}")
    # Return absolute path to ensure it can be found later
    return output_file.resolve()

