#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
import time
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types


VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ogv", ".ts", ".m2ts"
}


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def extract_first_5min_audio(input_video: Path, output_audio: Path) -> None:
    """Extract first 5 minutes of audio using stream copy if possible.

    Primary: copy AAC without re-encode to .m4a.
    Fallback: encode to AAC LC 192k if copy fails.
    """
    output_audio.parent.mkdir(parents=True, exist_ok=True)

    # Try stream copy (OBS AAC)
    copy_cmd = [
        "ffmpeg", "-y",
        "-ss", "0", "-t", "300",
        "-i", str(input_video),
        "-map", "0:a:0",
        "-c:a", "copy",
        "-vn",
        str(output_audio),
    ]
    result = subprocess.run(copy_cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return

    # Fallback: encode to AAC LC
    enc_cmd = [
        "ffmpeg", "-y",
        "-ss", "0", "-t", "300",
        "-i", str(input_video),
        "-map", "0:a:0",
        "-c:a", "aac", "-b:a", "192k",
        "-vn",
        str(output_audio),
    ]
    result2 = subprocess.run(enc_cmd, capture_output=True, text=True)
    if result2.returncode != 0:
        raise RuntimeError(
            f"Audio extraction failed for {input_video}\ncopy_stderr={result.stderr}\nenc_stderr={result2.stderr}"
        )


def transcribe_with_gemini(client: genai.Client, audio_path: Path) -> str:
    """Upload audio and request a transcript."""
    # Prefer m4a (audio/mp4)
    mime_type = "audio/mp4"

    # Attempt upload via Files API
    uploaded = None
    try:
        # Newer SDKs:
        uploaded = client.files.upload(file=str(audio_path), mime_type=mime_type)
    except Exception:
        try:
            # Alternate signature
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
            # Fallback to bytes
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
    # Some SDKs return a single response; others stream. Handle .text if present.
    text = getattr(resp, "text", None)
    if text is None:
        # Try to join candidates
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
    # Keep it to a single line and trim
    return (title.strip().splitlines() or [""])[0]


def _parse_retry_seconds_from_error(err: Exception) -> float:
    # Try to extract suggested wait time from error message
    m = re.search(r"retry in\s+([0-9.]+)s", str(err), re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            pass
    # Try to find RetryInfo retryDelay like '5s'
    m2 = re.search(r"retryDelay'?\s*:\s*'?(\d+)(s)?'?", str(err), re.IGNORECASE)
    if m2:
        try:
            return float(m2.group(1))
        except Exception:
            pass
    # Default backoff
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
            # Only retry on 429/RESOURCE_EXHAUSTED
            if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
                wait_s = _parse_retry_seconds_from_error(e)
                time.sleep(wait_s)
                attempt += 1
                continue
            raise
    # Exhausted retries
    raise last_err  # type: ignore[misc]


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Extract first 5 minutes of audio, transcribe with Gemini, and generate a YouTube title.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python transcribe_and_title.py --input-dir /Users/mahmoud/Desktop/trimmed --output-dir /Users/mahmoud/Desktop/temp
        """,
    )
    parser.add_argument("input_dir", help="Input directory containing trimmed videos")
    # Output dir is derived as sibling 'temp'
    parser.add_argument("--output-dir", default=None, help="Override output directory; default is sibling 'temp'")
    parser.add_argument("--force", action="store_true", help="Recreate outputs if they already exist")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir) if args.output_dir else (input_dir.parent / "temp")
    output_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set in environment", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    videos = [p for p in input_dir.iterdir() if p.is_file() and is_video_file(p)]
    if not videos:
        print(f"No videos found in {input_dir}")
        return

    print(f"Found {len(videos)} video(s) in {input_dir}")

    for idx, video in enumerate(sorted(videos), start=1):
        basename = video.stem
        audio_path = output_dir / f"{basename}.m4a"
        transcript_path = output_dir / f"{basename}.txt"
        title_path = output_dir / f"{basename}.title.txt"

        print(f"\n[{idx}/{len(videos)}] Processing: {video.name}")
        print(f"Audio (5 min) -> {audio_path}")

        if not audio_path.exists() or args.force:
            extract_first_5min_audio(video, audio_path)
        else:
            print("Audio already exists (skipping extraction). Use --force to re-extract.")

        # Transcribe
        if not transcript_path.exists() or args.force:
            print("Transcribing with Gemini...")
            transcript = transcribe_with_gemini(client, audio_path)
            if not transcript.strip():
                print("Warning: Empty transcript returned")
            transcript_path.write_text(transcript, encoding="utf-8")
            print(f"Transcript -> {transcript_path}")
        else:
            transcript = transcript_path.read_text(encoding="utf-8")
            print("Transcript already exists (skipping). Use --force to recreate.")

        # Title
        if not title_path.exists() or args.force:
            print("Generating YouTube title...")
            title = generate_title_with_gemini(client, transcript)
            title_path.write_text(title, encoding="utf-8")
            print(f"Title -> {title_path}")
        else:
            print("Title already exists (skipping). Use --force to recreate.")

    print("\nAll done.")


if __name__ == "__main__":
    main()


