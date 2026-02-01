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
    build_ffmpeg_cmd,
    calculate_resulting_length,
    detect_silence_points,
    find_optimal_padding,
    print_ffmpeg_cmd,
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


def _get_hevc_qsv_quality_params() -> list[str]:
    """hevc_qsv with ICQ (Intelligent Constant Quality). -global_quality selects ICQ mode (1=best .. 51=worst); ~25 ≈ crf 23."""
    return ["-preset", "slow", "-global_quality", "25"]


def _get_libx264_quality_params() -> list[str]:
    """Only the slower preset for libx264; everything else uses encoder defaults."""
    return ["-preset", "medium", "-profile:v", "high"]


def _build_segments_to_keep(
    input_file: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
) -> tuple[list[tuple[float, float]], float]:
    """Build segments_to_keep list using same algorithm as full trim. Returns (segments_to_keep, duration_sec)."""
    silence_starts, silence_ends = detect_silence_points(input_file, noise_threshold, min_duration, debug=DEBUG)
    duration_sec = _probe_duration(input_file)
    if duration_sec <= 0:
        raise ValueError(f"Invalid video duration: {duration_sec}s. Video file may be corrupted or empty.")
    if len(silence_starts) > len(silence_ends):
        silence_ends.append(duration_sec)

    if target_length is not None:
        if target_length >= duration_sec:
            return ([(0.0, round(duration_sec, 3))], duration_sec)
        optimal_pad = find_optimal_padding(silence_starts, silence_ends, duration_sec, target_length)
        pad_sec = optimal_pad

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
        print(f"[debug] total segments_to_keep={len(segments_to_keep)} sample={segments_to_keep[:5]}")
    return (segments_to_keep, duration_sec)


def create_silence_removed_audio(
    input_file: Path,
    output_audio_path: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float] = None,
    max_duration: Optional[float] = None,
    debug: bool = False,
) -> Path:
    """Create silence-removed audio (same algorithm as video trim), audio only (-vn).
    If max_duration is set (e.g. 300), limit output to that many seconds (e.g. first 5 min)."""
    global DEBUG
    DEBUG = debug
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)

    segments_to_keep, duration_sec = _build_segments_to_keep(
        input_file, noise_threshold, min_duration, pad_sec, target_length
    )

    if len(segments_to_keep) == 0:
        print("Warning: All audio detected as silence. Creating minimal audio.")
        cmd = build_ffmpeg_cmd(overwrite=True)
        cmd.extend([
            "-i", str(input_file),
            "-t", "0.1", "-vn",
            "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(output_audio_path),
        ])
        print_ffmpeg_cmd(cmd)
        subprocess.run(cmd, check=True)
        wait_for_file_release(output_audio_path)
        return output_audio_path.resolve()

    # Audio-only filter: atrim each segment, then concat
    filter_chains = "".join(
        f"[0:a]atrim=start={seg_start}:end={seg_end},asetpts=PTS-STARTPTS[a{i}];"
        for i, (seg_start, seg_end) in enumerate(segments_to_keep)
    )
    concat_inputs = "".join(f"[a{i}]" for i in range(len(segments_to_keep)))
    filter_complex = f"{filter_chains}{concat_inputs}concat=n={len(segments_to_keep)}:v=0:a=1[outa]"

    with tempfile.NamedTemporaryFile("w", suffix=".ffscript", delete=False, encoding="utf-8") as tf:
        tf.write(filter_complex)
        filter_script_path: str = tf.name
    cmd = build_ffmpeg_cmd(overwrite=True)
    cmd.extend([
        "-i", str(input_file),
        "-filter_complex_script", filter_script_path,
        "-map", "[outa]", "-vn",
        "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1",
    ])
    if max_duration is not None:
        cmd.extend(["-t", str(int(max_duration))])
    cmd.append(str(output_audio_path))
    try:
        print_ffmpeg_cmd(cmd)
        subprocess.run(cmd, check=True)
    finally:
        try:
            Path(filter_script_path).unlink(missing_ok=True)
        except Exception:
            pass

    wait_for_file_release(output_audio_path)
    print(f"Silence-removed audio -> {output_audio_path}")
    return output_audio_path.resolve()


def trim_single_video(
    input_file: Path,
    output_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
    debug: bool = False,
    output_basename: Optional[str] = None,
) -> Path:
    """Trim a single video and return the output file path."""
    global DEBUG
    DEBUG = debug
    
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = output_basename if output_basename is not None else input_file.stem
    output_file = (output_dir / f"{basename}.mp4").resolve()

    segments_to_keep, duration_sec = _build_segments_to_keep(
        input_file, noise_threshold, min_duration, pad_sec, target_length
    )

    if target_length is not None and target_length >= duration_sec:
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
    if target_length is not None:
        resulting_length = sum(end - start for start, end in segments_to_keep)
        print(f"Target length: {target_length}s")
        print(f"Expected resulting length: {resulting_length:.3f}s")

    # Handle case where all audio is silence (no segments to keep)
    if len(segments_to_keep) == 0:
        print("Warning: All audio detected as silence. Creating minimal video (first frame only).")
        # Create minimal video with first frame and silence; try hevc_qsv then libx264
        last_exc = None
        for codec, quality_params in [
            ("hevc_qsv", _get_hevc_qsv_quality_params()),
            ("libx264", _get_libx264_quality_params()),
        ]:
            cmd = build_ffmpeg_cmd(overwrite=True)
            cmd.extend(["-i", str(input_file), "-t", "0.1", "-c:v", codec])
            cmd.extend(quality_params)
            cmd.extend(["-c:a", "aac", "-b:a", AUDIO_BITRATE, str(output_file)])
            print_ffmpeg_cmd(cmd)
            try:
                subprocess.run(cmd, check=True)
                wait_for_file_release(output_file)
                print(f"Done! Output saved to: {output_file}")
                return output_file.resolve()
            except subprocess.CalledProcessError as e:
                last_exc = e
                if codec == "hevc_qsv":
                    print("hevc_qsv failed, falling back to libx264", file=sys.stderr)
        raise RuntimeError("Both hevc_qsv and libx264 failed for minimal video") from last_exc

    filter_chains = ''.join(
        (
            f"[0:v]trim=start={segment_start}:end={segment_end},setpts=PTS-STARTPTS[v{segment_index}];"
            f"[0:a]atrim=start={segment_start}:end={segment_end},asetpts=PTS-STARTPTS[a{segment_index}];"
        )
        for segment_index, (segment_start, segment_end) in enumerate(segments_to_keep)
    )
    concat_inputs = ''.join(f"[v{i}][a{i}]" for i in range(len(segments_to_keep)))
    filter_complex = f"{filter_chains}{concat_inputs}concat=n={len(segments_to_keep)}:v=1:a=1[outv][outa]"

    # Try hevc_qsv first (ICQ quality), fallback to libx264.
    ENCODERS_TO_TRY = [
        ("hevc_qsv", _get_hevc_qsv_quality_params()),
        ("libx264", _get_libx264_quality_params()),
    ]

    with tempfile.NamedTemporaryFile("w", suffix=".ffscript", delete=False, encoding="utf-8") as tf:
        tf.write(filter_complex)
        filter_script_path: str = tf.name

    def build_encode_cmd(codec: str, quality_params: list[str]) -> list[str]:
        cmd = build_ffmpeg_cmd(overwrite=True)
        cmd.extend(["-i", str(input_file)])
        cmd.extend(["-filter_complex_script", filter_script_path])
        cmd.extend([
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", codec,
        ])
        cmd.extend(quality_params)
        cmd.extend(["-c:a", "aac", "-b:a", AUDIO_BITRATE, str(output_file)])
        return cmd

    try:
        print(f"Input: {input_file}")
        print(f"Output: {output_file}")
        print(f"Settings: noise={noise_threshold}dB, min_duration={min_duration}s, pad={pad_sec}s")
        print(f"Filter complex length: {len(filter_complex)} characters")
        print(f"Number of segments: {len(segments_to_keep)}")
        last_exc = None
        last_cmd = None
        for codec, quality_params in ENCODERS_TO_TRY:
            cmd = build_encode_cmd(codec, quality_params)
            print_ffmpeg_cmd(cmd)
            last_cmd = cmd
            try:
                subprocess.run(cmd, check=True)
                break
            except subprocess.CalledProcessError as e:
                last_exc = e
                if codec == "hevc_qsv":
                    print("hevc_qsv failed, falling back to libx264", file=sys.stderr)
        else:
            if last_exc is not None:
                raise subprocess.CalledProcessError(
                    last_exc.returncode, last_cmd or [], last_exc.stdout, last_exc.stderr
                ) from last_exc
    finally:
        try:
            Path(filter_script_path).unlink(missing_ok=True)
        except Exception:
            pass

    wait_for_file_release(output_file)
    print(f"Done! Output saved to: {output_file}")
    return output_file.resolve()

