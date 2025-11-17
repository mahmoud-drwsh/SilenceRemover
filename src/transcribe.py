"""Video transcription and title generation functionality."""

import random
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Error: Google GenAI SDK not installed. Install 'google-genai' to use transcribe/title.", file=sys.stderr)
    sys.exit(1)

from src.main_utils import (
    AUDIO_BITRATE,
    COOLDOWN_BETWEEN_GEMINI_CALLS_SEC,
    TRANSCRIBE_PROMPT,
    TITLE_PROMPT_TEMPLATE,
    build_ffmpeg_cmd,
)


def extract_first_5min_audio(input_video: Path, output_audio: Path) -> None:
    output_audio.parent.mkdir(parents=True, exist_ok=True)
    copy_cmd = build_ffmpeg_cmd(overwrite=True)
    copy_cmd.extend([
        "-ss", "0", "-t", "300",
        "-i", str(input_video),
        "-map", "0:a:0", "-c:a", "copy", "-vn",
        str(output_audio),
    ])
    r = subprocess.run(copy_cmd, capture_output=True, text=True)
    if r.returncode == 0:
        return
    enc_cmd = build_ffmpeg_cmd(overwrite=True)
    enc_cmd.extend([
        "-ss", "0", "-t", "300",
        "-i", str(input_video),
        "-map", "0:a:0", "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-vn",
        str(output_audio),
    ])
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


def transcribe_single_video(trimmed_video: Path, temp_dir: Path, client, basename: str) -> tuple[Path, Path]:
    """Transcribe a single trimmed video. Returns (transcript_path, title_path). Skips if files exist."""
    audio_path = temp_dir / f"{basename}.m4a"
    transcript_path = temp_dir / f"{basename}.txt"
    title_path = temp_dir / f"{basename}.title.txt"

    if not audio_path.exists():
        print(f"Extracting audio (5 min) -> {audio_path}")
        extract_first_5min_audio(trimmed_video, audio_path)
    else:
        print("Audio already exists (skipping extraction).")

    if not transcript_path.exists():
        print("Transcribing with Gemini...")
        transcript = transcribe_with_gemini(client, audio_path)
        transcript_path.write_text(transcript, encoding="utf-8")
        print(f"Transcript -> {transcript_path}")
    else:
        print("Transcript already exists (skipping).")

    # Ensure spacing between transcript and title calls
    time.sleep(COOLDOWN_BETWEEN_GEMINI_CALLS_SEC)
    if not title_path.exists():
        print("Generating YouTube title...")
        transcript_text = transcript_path.read_text(encoding="utf-8")
        title = generate_title_with_gemini(client, transcript_text)
        title_path.write_text(title, encoding="utf-8")
        print(f"Title -> {title_path}")
    else:
        print("Title already exists (skipping).")

    return transcript_path, title_path

