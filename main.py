#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
import time
import sys
import shutil
import random
import tempfile
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types


# --- Inline helpers from src/common.py ---

# Debug flag (set from CLI)
DEBUG = False

# Configurables
MAX_PAD_SEC = 10.0
PAD_INCREMENT_SEC = 0.01
BITRATE_FALLBACK_BPS = 3_000_000
AUDIO_BITRATE = "192k"
PREFERRED_VIDEO_ENCODERS = [
    "hevc_qsv",
    "h264_qsv",
    "h264_videotoolbox",
    "h264_amf",
]
COOLDOWN_BETWEEN_GEMINI_CALLS_SEC = 2.0

TRANSCRIBE_PROMPT = """Transcribe the audio as clean verbatim text in Arabic.
- No timestamps
- No speaker labels
- Keep punctuation and natural phrasing."""

TITLE_PROMPT_TEMPLATE = (
    "You are generating a YouTube video title in Arabic.\n"
    "Constraints:\n"
    "- Propose exactly one concise title (<= 100 characters).\n"
    "- Prefer using words verbatim from the transcript wherever possible.\n"
    "- No quotes, no extra commentary. Title only.\n"
    "- When a certain book is mentioned in the transcript as the book being taught, use the book name in the title using the following format: (book name) (title)."
    "- When a lesson number is mentioned in the transcript as the lesson being taught, use the lesson number in the title using the following format: (lesson number) (book name) (title).\n"
    """ِAVOID REPEATING THE NUMBER IN TEXT FORM in the title after the book name. the number can only be in the beginning as shown below.

EXAMPLES:
41 - ألفية ابن مالك - النحو الفاعل واحكامه
42 - الكوكب الساطع - الكناية والتعريض واحكامهما ولمحة عن الحروف
73 - كنز الدقائق - التولية والمرابحة والتصرف في المبيع قبل قبضه
43 - الكوكب الساطع - معاني اذا وان واو واي
9 - العقيدة الطحاوية - القران قديم ام مخلوق ومذاهب الناس في ذلك
9 - أحكام القرآن - احكام الدم و دم سيدنا رسول الله صلى الله عليه وسلم
9 - الموطأ - فضل الجهاد واحكام الجنائز
10 - العقيدة الطحاوية - كيف تسربت الوثنية الى الاديان اليهودية والمسيحية والاسلام ورؤية الله تعالى يوم القيامة
10 - احكام القران - تفسير اية الحيض واختلاف الفقهاء فيها
10 - موطأ الإمام مالك - أحكام الزكاة.\n"""
    "- When no book or lesson number is mentioned, use the title as is.\n"
    "\n\n"
    "Transcript:\n{transcript}\n"
)

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ogv", ".ts", ".m2ts",
}


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def sibling_dir(base_dir: Path, name: str) -> Path:
    d = base_dir.parent / name
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- Early validation helpers ---

def _fail(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def _require_tools(*tools: str) -> None:
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        _fail(f"Required tool(s) not found on PATH: {', '.join(missing)}")


def _require_input_dir(input_dir: Path) -> None:
    if not input_dir.exists() or not input_dir.is_dir():
        _fail(f"Input directory does not exist: {input_dir}")


def _require_videos_in(input_dir: Path) -> None:
    try:
        has_video = any(is_video_file(p) for p in input_dir.iterdir())
    except FileNotFoundError:
        has_video = False
    if not has_video:
        _fail(f"No video files found in '{input_dir}'")


def _require_gemini() -> None:
    try:
        import google.genai  # noqa: F401
    except Exception:
        _fail("Google GenAI SDK not installed. Install 'google-genai' to use transcribe/title.")
    if not os.environ.get("GEMINI_API_KEY"):
        _fail("GEMINI_API_KEY not set (load via .env or environment).")


# --- Trimming core (from src/remove_silence.py) ---

def calculate_resulting_length(silence_starts: list[float], silence_ends: list[float], duration_sec: float, pad_sec: float) -> float:
    if len(silence_starts) != len(silence_ends):
        if len(silence_starts) > len(silence_ends):
            silence_ends = list(silence_ends) + [duration_sec]
        else:
            silence_ends = list(silence_ends)
    segments_to_keep: list[tuple[float, float]] = []
    prev_end = 0.0
    for silence_start, silence_end in zip(silence_starts, silence_ends):
        if silence_end - silence_start <= pad_sec * 2:
            continue
        if silence_start > prev_end:
            segment_start = round(prev_end, 3)
            segment_end = round(silence_start + pad_sec, 3)
            segments_to_keep.append((segment_start, segment_end))
        prev_end = max(0.0, silence_end - pad_sec)
    if prev_end < duration_sec:
        segments_to_keep.append((round(prev_end, 3), round(duration_sec, 3)))
    return sum(end - start for start, end in segments_to_keep)


def find_optimal_padding(silence_starts: list[float], silence_ends: list[float], duration_sec: float, target_length: float) -> float:
    if not silence_starts:
        return 0.0
    result_with_0 = calculate_resulting_length(silence_starts, silence_ends, duration_sec, 0.0)
    if target_length >= duration_sec:
        return 0.0
    if result_with_0 > target_length:
        return 0.0
    max_pad = MAX_PAD_SEC
    pad_increment = PAD_INCREMENT_SEC
    current_pad = 0.0
    best_pad = 0.0
    while current_pad <= max_pad:
        resulting_length = calculate_resulting_length(silence_starts, silence_ends, duration_sec, current_pad)
        if resulting_length < target_length:
            best_pad = current_pad
        else:
            break
        current_pad += pad_increment
    return round(best_pad, 3)


def _detect_silence_points(input_file: Path, noise_threshold: float, min_duration: float) -> tuple[list[float], list[float]]:
    silence_filter = f"silencedetect=n={noise_threshold}dB:d={min_duration}"

    # Prefer hardware acceleration if available; otherwise rely on CPU.
    def _choose_hwaccel() -> str | None:
        try:
            out = subprocess.run(["ffmpeg", "-hide_banner", "-hwaccels"], capture_output=True, text=True).stdout
        except Exception:
            return None
        preferred = ["videotoolbox", "cuda", "qsv", "d3d11va", "dxva2", "vaapi"]
        available = {line.strip() for line in out.splitlines() if line.strip() and not line.startswith("Hardware acceleration methods")}
        for hw in preferred:
            if hw in available:
                return hw
        return None

    hwaccel = _choose_hwaccel()
    cmd = ["ffmpeg", "-hide_banner", "-y"]
    if hwaccel:
        cmd += ["-hwaccel", hwaccel]
    # Audio-only analysis: skip video/subtitle/data decoding for speed
    cmd += ["-vn", "-sn", "-dn", "-i", str(input_file), "-map", "0:a:0", "-af", silence_filter, "-f", "null", "-"]

    result = subprocess.run(
        cmd,
        stderr=subprocess.PIPE,
        text=True,
    ).stderr
    if DEBUG:
        print(f"[debug] silencedetect filter: {silence_filter}")
        if hwaccel:
            print(f"[debug] using hwaccel: {hwaccel}")
        print(f"[debug] ffmpeg cmd: {' '.join(cmd)}")
        print(f"[debug] Raw FFmpeg silencedetect output (showing lines with 'silence_'):")
        for line in result.splitlines():
            if "silence_" in line:
                print(f"[debug] {line}")
    silence_starts = [float(x) for x in re.findall(r"silence_start: (-?\d+\.?\d*)", result)]
    silence_ends = [float(x) for x in re.findall(r"silence_end: (\d+\.?\d*)", result)]
    if DEBUG:
        print(f"[debug] Parsed counts: starts={len(silence_starts)} ends={len(silence_ends)}")
        if silence_starts:
            print(f"[debug] First start={silence_starts[0]} last start={silence_starts[-1]}")
        if silence_ends:
            print(f"[debug] First end  ={silence_ends[0]} last end  ={silence_ends[-1]}")
        print(f"[debug] Parsed silence_starts={silence_starts[:10]}{'...' if len(silence_starts)>10 else ''}")
        print(f"[debug] Parsed silence_ends  ={silence_ends[:10]}{'...' if len(silence_ends)>10 else ''}")
    return silence_starts, silence_ends


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
    available_encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return next((c for c in PREFERRED_VIDEO_ENCODERS if c in available_encoders), "libx264")


def trim_single_video(input_file: Path, output_dir: Path, noise_threshold: float, min_duration: float, pad_sec: float, target_length: Optional[float]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = input_file.stem
    extension = input_file.suffix or ".mp4"
    output_file = output_dir / f"{basename}{extension}"

    silence_starts, silence_ends = _detect_silence_points(input_file, noise_threshold, min_duration)
    duration_sec = _probe_duration(input_file)
    if len(silence_starts) > len(silence_ends):
        silence_ends.append(duration_sec)

    if target_length is not None:
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
            seg = (round(prev_end, 3), round(silence_start + pad_sec, 3))
            segments_to_keep.append(seg)
            if DEBUG:
                print(f"[debug] add segment keep={seg} from prev_end={prev_end:.3f} and silence_start={silence_start:.3f} pad={pad_sec:.3f}")
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
        cmd = [
            "ffmpeg", "-y", "-i", str(input_file),
            "-filter_complex_script", filter_script_path,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", video_codec, "-b:v", str(bitrate_bps),
            "-c:a", "aac", "-b:a", AUDIO_BITRATE, str(output_file),
        ]
    except Exception:
        # Fallback to inline filter if script creation fails
        cmd = [
            "ffmpeg", "-y", "-i", str(input_file),
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", video_codec, "-b:v", str(bitrate_bps),
            "-c:a", "aac", "-b:a", AUDIO_BITRATE, str(output_file),
        ]

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
    print(f"Done! Output saved to: {output_file}")


def run_trim_directory(input_dir: Path, target_length: Optional[float]) -> None:
    output_dir = sibling_dir(input_dir, "trimmed")
    videos = sorted(p for p in input_dir.iterdir() if is_video_file(p))
    if not videos:
        print(f"No video files found in '{input_dir}'")
        return

    load_dotenv()
    noise_threshold = float(os.getenv("NOISE_THRESHOLD", "-30.0"))
    min_duration = float(os.getenv("MIN_DURATION", "0.5"))
    pad_default = float(os.getenv("PAD", "0.5"))

    print(f"Found {len(videos)} video file(s) to process")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    print("-" * 60)

    # Filter out videos that have already been trimmed
    # Check if the specific output file exists (preserving extension) rather than just checking stems
    def get_output_path(input_video: Path) -> Path:
        basename = input_video.stem
        extension = input_video.suffix or ".mp4"
        return output_dir / f"{basename}{extension}"
    
    videos_to_process = [v for v in videos if not get_output_path(v).exists()]

    if not videos_to_process:
        print("All videos appear to be trimmed already. Nothing to do.")
        return

    num_skipped = len(videos) - len(videos_to_process)
    if num_skipped > 0:
        print(f"Skipping {num_skipped} video(s) that already exist in the output directory.")

    for i, video_file in enumerate(videos_to_process, 1):
        print(f"\n[{i}/{len(videos_to_process)}] Processing: {video_file.name}")
        trim_single_video(
            input_file=video_file,
            output_dir=output_dir,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_default,
            target_length=target_length,
        )


# --- Transcription and title (from src/transcribe_and_title.py) ---

def extract_first_5min_audio(input_video: Path, output_audio: Path) -> None:
    output_audio.parent.mkdir(parents=True, exist_ok=True)
    copy_cmd = [
        "ffmpeg", "-y", "-ss", "0", "-t", "300",
        "-i", str(input_video),
        "-map", "0:a:0", "-c:a", "copy", "-vn",
        str(output_audio),
    ]
    r = subprocess.run(copy_cmd, capture_output=True, text=True)
    if r.returncode == 0:
        return
    enc_cmd = [
        "ffmpeg", "-y", "-ss", "0", "-t", "300",
        "-i", str(input_video),
        "-map", "0:a:0", "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-vn",
        str(output_audio),
    ]
    r2 = subprocess.run(enc_cmd, capture_output=True, text=True)
    if r2.returncode != 0:
        raise RuntimeError(
            f"Audio extraction failed for {input_video}\ncopy_stderr={r.stderr}\nenc_stderr={r2.stderr}"
        )


def _parse_retry_seconds_from_error(err: Exception) -> float:
    m = re.search(r"retry in\s+([0-9.]+)s", str(err), re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            pass
    m2 = re.search(r"retryDelay'?\s*:\s*'?(\d+)(s)?'?", str(err), re.IGNORECASE)
    if m2:
        try:
            return float(m2.group(1))
        except Exception:
            pass
    return 6.0


def _generate_with_retry(
    client,
    model: str,
    contents,
    max_attempts: int = 5,
    initial_backoff_sec: float = 1.0,
    max_backoff_sec: float = 30.0,
    multiplier: float = 2.0,
    jitter_ratio: float = 0.2,
):
    attempt = 0
    last_err: Exception | None = None
    while attempt < max_attempts:
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config={"thinking_config": {"thinking_budget": -1}},
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            last_err = e
            # Base delay may be suggested by server error text
            suggested_delay = _parse_retry_seconds_from_error(e)
            # Exponential backoff with jitter
            exp_delay = initial_backoff_sec * (multiplier ** attempt)
            base_delay = max(suggested_delay, exp_delay)
            delay = min(max_backoff_sec, base_delay)
            if jitter_ratio > 0:
                delay *= random.uniform(max(0.0, 1 - jitter_ratio), 1 + jitter_ratio)
            time.sleep(delay)
            attempt += 1
            continue
    raise last_err  # type: ignore[misc]


def transcribe_with_gemini(client, audio_path: Path) -> str:
    mime_type = "audio/mp4"
    uploaded = None
    try:
        uploaded = client.files.upload(file=str(audio_path), mime_type=mime_type)
    except Exception:
        try:
            uploaded = client.files.upload(path=str(audio_path), mime_type=mime_type)
        except Exception:
            uploaded = None

    parts = [types.Part.from_text(text=TRANSCRIBE_PROMPT)]
    if uploaded is not None:
        try:
            parts.append(types.Part.from_uri(mime_type=mime_type, file_uri=uploaded.uri))
        except Exception:
            data = audio_path.read_bytes()
            parts.append(types.Part.from_bytes(data=data, mime_type=mime_type))
    else:
        data = audio_path.read_bytes()
        parts.append(types.Part.from_bytes(data=data, mime_type=mime_type))

    # Proactive cooldown to keep under free-tier rate limits
    time.sleep(COOLDOWN_BETWEEN_GEMINI_CALLS_SEC)
    resp = _generate_with_retry(
        client=client,
        model="gemini-flash-latest",
        contents=[types.Content(role="user", parts=parts)],
    )
    text = getattr(resp, "text", None)
    if text is None:
        try:
            text = "".join([c.output_text for c in resp.candidates if getattr(c, "output_text", None)])
        except Exception:
            text = ""
    return text or ""


def generate_title_with_gemini(client, transcript: str) -> str:
    prompt = TITLE_PROMPT_TEMPLATE.format(transcript=transcript)
    # Proactive cooldown to keep under free-tier rate limits
    time.sleep(COOLDOWN_BETWEEN_GEMINI_CALLS_SEC)
    resp = _generate_with_retry(
        client=client,
        model="gemini-flash-latest",
        contents=[
            types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
        ],
    )
    title = getattr(resp, "text", "") or ""
    return (title.strip().splitlines() or [""])[0]


def run_transcribe_directory(input_dir: Path, force: bool = False) -> None:
    load_dotenv()
    out_dir = sibling_dir(input_dir, "temp")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    client = genai.Client(api_key=api_key)

    videos = [p for p in input_dir.iterdir() if is_video_file(p)]
    if not videos:
        print(f"No videos found in {input_dir}")
        return
    print(f"Found {len(videos)} video(s) in {input_dir}")

    for idx, video in enumerate(sorted(videos), start=1):
        basename = video.stem
        audio_path = out_dir / f"{basename}.m4a"
        transcript_path = out_dir / f"{basename}.txt"
        title_path = out_dir / f"{basename}.title.txt"

        print(f"\n[{idx}/{len(videos)}] Processing: {video.name}")
        if not audio_path.exists() or force:
            print(f"Audio (5 min) -> {audio_path}")
            extract_first_5min_audio(video, audio_path)
        else:
            print("Audio already exists (skipping extraction). Use --force to re-extract.")

        if not transcript_path.exists() or force:
            print("Transcribing with Gemini...")
            transcript = transcribe_with_gemini(client, audio_path)
            transcript_path.write_text(transcript, encoding="utf-8")
            print(f"Transcript -> {transcript_path}")
        else:
            print("Transcript already exists (skipping). Use --force to recreate.")

        # Ensure spacing between transcript and title calls
        time.sleep(COOLDOWN_BETWEEN_GEMINI_CALLS_SEC)
        if not title_path.exists() or force:
            print("Generating YouTube title...")
            title = generate_title_with_gemini(client, transcript_path.read_text(encoding="utf-8"))
            title_path.write_text(title, encoding="utf-8")
            print(f"Title -> {title_path}")
        else:
            print("Title already exists (skipping). Use --force to recreate.")

    print("\nAll done.")


# --- Rename (from src/rename_from_titles.py) ---

def _sanitize_filename(name: str) -> str:
    cleaned = "".join(c for c in name if c not in "\0\n\r\t").strip().strip('"').strip("'")
    for ch in ["/", "\\", ":", "*", "?", "\"", "<", ">", "|"]:
        cleaned = cleaned.replace(ch, " ")
    return (" ".join(cleaned.split()) or "untitled")[:200]


def run_rename_directory(input_dir: Path) -> None:
    temp_dir = sibling_dir(input_dir, "temp")
    renamed_dir = sibling_dir(input_dir, "renamed")
    trimmed_dir = sibling_dir(input_dir, "trimmed")

    videos = sorted(p for p in trimmed_dir.iterdir() if is_video_file(p))
    if not videos:
        print(f"No video files found in '{trimmed_dir}'")
        return

    print(f"Found {len(videos)} file(s). Writing to: {renamed_dir}")
    seen: set[str] = set()
    for i, video in enumerate(videos, 1):
        basename = video.stem
        title_file = temp_dir / f"{basename}.title.txt"
        new_base: Optional[str] = None
        if title_file.exists():
            raw = title_file.read_text(encoding="utf-8").strip()
            if raw:
                new_base = _sanitize_filename(raw)
        if not new_base:
            new_base = _sanitize_filename(basename)

        candidate = new_base
        k = 1
        while (candidate.lower() in seen) or (renamed_dir / f"{candidate}{video.suffix}").exists():
            candidate = f"{new_base}-{k}"
            k += 1
        seen.add(candidate.lower())
        dest = renamed_dir / f"{candidate}{video.suffix}"
        print(f"[{i}/{len(videos)}] {video.name} -> {dest.name}")
        shutil.copy2(video, dest)

    print("Done.")


def run_rename_originals(input_dir: Path) -> None:
    temp_dir = sibling_dir(input_dir, "temp")
    renamed_dir = sibling_dir(input_dir, "renamed")

    videos = sorted(p for p in input_dir.iterdir() if is_video_file(p))
    if not videos:
        print(f"No video files found in '{input_dir}'")
        return

    print(f"Found {len(videos)} file(s). Writing to: {renamed_dir}")
    seen: set[str] = set()
    for i, video in enumerate(videos, 1):
        basename = video.stem
        title_file = temp_dir / f"{basename}.title.txt"
        new_base: Optional[str] = None
        if title_file.exists():
            raw = title_file.read_text(encoding="utf-8").strip()
            if raw:
                new_base = _sanitize_filename(raw)
        if not new_base:
            new_base = _sanitize_filename(basename)

        candidate = new_base
        k = 1
        while (candidate.lower() in seen) or (renamed_dir / f"{candidate}{video.suffix}").exists():
            candidate = f"{new_base}-{k}"
            k += 1
        seen.add(candidate.lower())
        dest = renamed_dir / f"{candidate}{video.suffix}"
        print(f"[{i}/{len(videos)}] {video.name} -> {dest.name}")
        shutil.copy2(video, dest)

    print("Done.")


# --- CLI ---

def cmd_trim(ns: argparse.Namespace) -> None:
    input_dir = Path(ns.input_dir)
    _require_tools("ffmpeg", "ffprobe")
    _require_input_dir(input_dir)
    _require_videos_in(input_dir)
    run_trim_directory(input_dir, ns.target_length)


def cmd_transcribe(ns: argparse.Namespace) -> None:
    input_dir = Path(ns.input_dir)
    _require_tools("ffmpeg", "ffprobe")
    _require_input_dir(input_dir)
    _require_videos_in(input_dir)
    _require_gemini()
    run_transcribe_directory(input_dir, ns.force)


def cmd_rename(ns: argparse.Namespace) -> None:
    input_dir = Path(ns.input_dir)
    trimmed_dir = sibling_dir(input_dir, "trimmed")
    _require_input_dir(trimmed_dir)
    _require_videos_in(trimmed_dir)
    run_rename_directory(input_dir)


def cmd_transcribe_rename(ns: argparse.Namespace) -> None:
    input_dir = Path(ns.input_dir)
    _require_tools("ffmpeg", "ffprobe")
    _require_input_dir(input_dir)
    _require_videos_in(input_dir)
    _require_gemini()
    run_transcribe_directory(input_dir, ns.force)
    run_rename_originals(input_dir)


def cmd_all(ns: argparse.Namespace) -> None:
    # Validate everything up-front to fail early
    input_dir = Path(ns.input_dir)
    _require_tools("ffmpeg", "ffprobe")
    _require_input_dir(input_dir)
    _require_videos_in(input_dir)
    _require_gemini()
    cmd_trim(ns)
    cmd_transcribe(ns)
    cmd_rename(ns)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SilenceRemover CLI")
    p.add_argument("--debug", action="store_true", help="Print detailed debug logs (FFmpeg silencedetect, parsed values)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("trim", help="Trim videos in a folder")
    sp.add_argument("--input-dir", required=True)
    sp.add_argument("--target-length", type=float)
    sp.set_defaults(func=cmd_trim)

    sp = sub.add_parser("transcribe", help="Transcribe first 5 min and title")
    sp.add_argument("--input-dir", required=True)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_transcribe)

    sp = sub.add_parser("rename", help="Copy originals to renamed using titles")
    sp.add_argument("--input-dir", required=True)
    sp.set_defaults(func=cmd_rename)

    sp = sub.add_parser("transcribe-rename", help="Transcribe then rename originals (no trimming)")
    sp.add_argument("--input-dir", required=True)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_transcribe_rename)

    sp = sub.add_parser("all", help="Trim -> Transcribe -> Rename")
    sp.add_argument("--input-dir", required=True)
    sp.add_argument("--target-length", type=float)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_all)

    return p


def main() -> None:
    parser = build_parser()
    ns = parser.parse_args()
    load_dotenv()
    global DEBUG
    DEBUG = bool(getattr(ns, "debug", False))
    ns.func(ns)


if __name__ == '__main__':
    main()
