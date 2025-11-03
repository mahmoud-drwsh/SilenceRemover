from pathlib import Path
from typing import Optional
from .common import sibling_dir, is_video_file
from google import genai
from google.genai import types
import os
import subprocess
import time
import re
from dotenv import load_dotenv


def run(input_dir: Path, output_dir: Optional[Path] = None, force: bool = False) -> None:
    # Load .env so GEMINI_API_KEY and other vars are available
    load_dotenv()

    input_dir = Path(input_dir)
    out_dir = output_dir or sibling_dir(input_dir, "temp")

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

        transcript: str
        if not transcript_path.exists() or force:
            print("Transcribing with Gemini...")
            transcript = transcribe_with_gemini(client, audio_path)
            transcript_path.write_text(transcript, encoding="utf-8")
            print(f"Transcript -> {transcript_path}")
        else:
            transcript = transcript_path.read_text(encoding="utf-8")
            print("Transcript already exists (skipping). Use --force to recreate.")

        if not title_path.exists() or force:
            print("Generating YouTube title...")
            title = generate_title_with_gemini(client, transcript)
            title_path.write_text(title, encoding="utf-8")
            print(f"Title -> {title_path}")
        else:
            print("Title already exists (skipping). Use --force to recreate.")

    print("\nAll done.")


# --- Local implementations (avoid cross-package imports) ---

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
        "-map", "0:a:0", "-c:a", "aac", "-b:a", "192k", "-vn",
        str(output_audio),
    ]
    r2 = subprocess.run(enc_cmd, capture_output=True, text=True)
    if r2.returncode != 0:
        raise RuntimeError(f"Audio extraction failed for {input_video}\ncopy_stderr={r.stderr}\nenc_stderr={r2.stderr}")


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


def _generate_with_retry(client: genai.Client, model: str, contents: list[types.Content], max_attempts: int = 5):
    attempt = 0
    last_err: Exception | None = None
    while attempt < max_attempts:
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=-1)
                ),
            )
        except Exception as e:
            last_err = e
            msg = str(e)
            if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
                time.sleep(_parse_retry_seconds_from_error(e))
                attempt += 1
                continue
            raise
    raise last_err  # type: ignore[misc]


def transcribe_with_gemini(client: genai.Client, audio_path: Path) -> str:
    mime_type = "audio/mp4"
    uploaded = None
    try:
        uploaded = client.files.upload(file=str(audio_path), mime_type=mime_type)
    except Exception:
        try:
            uploaded = client.files.upload(path=str(audio_path), mime_type=mime_type)
        except Exception:
            uploaded = None

    parts = [
        types.Part.from_text(text=(
            "Transcribe the audio as clean verbatim text.\n"
            "- No timestamps\n- No speaker labels\n- Keep punctuation and natural phrasing."
        ))
    ]
    if uploaded is not None:
        try:
            parts.append(types.Part.from_uri(mime_type=mime_type, file_uri=uploaded.uri))
        except Exception:
            data = audio_path.read_bytes()
            parts.append(types.Part.from_bytes(data=data, mime_type=mime_type))
    else:
        data = audio_path.read_bytes()
        parts.append(types.Part.from_bytes(data=data, mime_type=mime_type))

    resp = _generate_with_retry(
        client=client,
        model="gemini-2.5-pro",
        contents=[types.Content(role="user", parts=parts)],
    )
    text = getattr(resp, "text", None)
    if text is None:
        try:
            text = "".join([c.output_text for c in resp.candidates if getattr(c, "output_text", None)])
        except Exception:
            text = ""
    return text or ""


def generate_title_with_gemini(client: genai.Client, transcript: str) -> str:
    prompt = (
        "You are generating a YouTube video title.\n"
        "Constraints:\n"
        "- Propose exactly one concise title (<= 70 characters).\n"
        "- Prefer using words verbatim from the transcript wherever possible.\n"
        "- No quotes, no extra commentary. Title only.\n\n"
        f"Transcript:\n{transcript}"
    )
    resp = _generate_with_retry(
        client=client,
        model="gemini-2.5-pro",
        contents=[
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)],
            )
        ],
    )
    title = getattr(resp, "text", "") or ""
    return (title.strip().splitlines() or [""])[0]


