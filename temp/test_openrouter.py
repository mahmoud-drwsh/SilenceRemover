#!/usr/bin/env python3
"""Test script for OpenRouter audio transcription (uses production sr_transcription API)."""

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

from src.ffmpeg.runner import run
from src.ffmpeg.transcode import build_audio_window_extract_command
from sr_transcription import transcribe_with_openrouter

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not OPENROUTER_API_KEY:
    print("Error: OPENROUTER_API_KEY not set in .env file", file=sys.stderr)
    sys.exit(1)


def extract_first_minute_audio(input_video: Path, output_audio: Path, format: str = "ogg") -> None:
    """Extract first 60 seconds of audio from video.

    Args:
        input_video: Input video file
        output_audio: Output audio file path
        format: Audio format (wav, m4a, mp3, etc.)
    """
    output_audio.parent.mkdir(parents=True, exist_ok=True)

    if format == "ogg":
        command = build_audio_window_extract_command(
            input_file=input_video,
            output_audio=output_audio,
            duration_seconds=60,
            codec_args=["-c:a", "libopus", "-ar", "16000", "-ac", "1", "-b:a", "32k"],
        )
    elif format == "m4a":
        copy_cmd = build_audio_window_extract_command(
            input_file=input_video,
            output_audio=output_audio,
            duration_seconds=60,
            codec_args=["-c:a", "copy"],
        )
        copy_result = run(copy_cmd, capture_output=True, text=True, check=False)
        if copy_result.returncode == 0:
            return
        command = build_audio_window_extract_command(
            input_file=input_video,
            output_audio=output_audio,
            duration_seconds=60,
            codec_args=["-c:a", "aac", "-b:a", "192k"],
        )
    else:
        raise ValueError("Unsupported audio format for this helper. Use 'ogg' or 'm4a'.")

    result = run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"Audio extraction failed for {input_video}\nstderr={result.stderr}"
        )


def main() -> None:
    """Test OpenRouter transcription on first video in test directory."""
    test_dir = Path("/Users/mahmoud/Desktop/VIDS/raw")
    temp_dir = Path("/Users/mahmoud/Desktop/VIDS/temp")
    temp_dir.mkdir(parents=True, exist_ok=True)

    video_files = sorted([f for f in test_dir.iterdir() if f.suffix == ".mkv"])
    if not video_files:
        print(f"No video files found in {test_dir}", file=sys.stderr)
        sys.exit(1)

    test_video = video_files[0]
    print(f"Testing with: {test_video.name}")
    print("=" * 60)

    audio_output = temp_dir / f"{test_video.stem}_1min.ogg"
    print("\n[1/2] Extracting first minute of audio as OGG...")
    extract_first_minute_audio(test_video, audio_output, format="ogg")
    print(f"Audio extracted: {audio_output}")

    model = "google/gemini-3.1-flash-lite-preview"
    print(f"\n[2/2] Transcribing via sr_transcription (model: {model})")
    print("-" * 60)

    try:
        text = transcribe_with_openrouter(
            OPENROUTER_API_KEY,
            audio_output,
            model=model,
            log_dir=temp_dir,
        )
        print("\nTranscription result:")
        print("=" * 60)
        print(text)
        print("=" * 60)

        transcript_path = temp_dir / f"{test_video.stem}_openrouter_transcript.txt"
        transcript_path.write_text(text, encoding="utf-8")
        print(f"\nTranscript saved: {transcript_path}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Test complete!")


if __name__ == "__main__":
    main()
