#!/usr/bin/env python3
"""Test script for OpenRouter audio transcription."""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not OPENROUTER_API_KEY:
    print("Error: OPENROUTER_API_KEY not set in .env file", file=sys.stderr)
    sys.exit(1)


def extract_first_minute_audio(input_video: Path, output_audio: Path, format: str = "wav") -> None:
    """Extract first 60 seconds of audio from video.
    
    Args:
        input_video: Input video file
        output_audio: Output audio file path
        format: Audio format (wav, m4a, mp3, etc.)
    """
    output_audio.parent.mkdir(parents=True, exist_ok=True)
    
    # Convert to specified format
    if format == "wav":
        enc_cmd = [
            "ffmpeg", "-hide_banner", "-y",
            "-ss", "0", "-t", "60",  # First 60 seconds
            "-i", str(input_video),
            "-map", "0:a:0", "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", "-vn",  # WAV format, 16kHz mono
            str(output_audio),
        ]
    elif format == "m4a":
        # Try to copy audio stream first
        copy_cmd = [
            "ffmpeg", "-hide_banner", "-y",
            "-ss", "0", "-t", "60",
            "-i", str(input_video),
            "-map", "0:a:0", "-c:a", "copy", "-vn",
            str(output_audio),
        ]
        r = subprocess.run(copy_cmd, capture_output=True, text=True)
        if r.returncode == 0:
            return
        # Fallback: encode to aac
        enc_cmd = [
            "ffmpeg", "-hide_banner", "-y",
            "-ss", "0", "-t", "60",
            "-i", str(input_video),
            "-map", "0:a:0", "-c:a", "aac", "-b:a", "192k", "-vn",
            str(output_audio),
        ]
    else:
        enc_cmd = [
            "ffmpeg", "-hide_banner", "-y",
            "-ss", "0", "-t", "60",
            "-i", str(input_video),
            "-map", "0:a:0", "-vn",
            str(output_audio),
        ]
    
    r2 = subprocess.run(enc_cmd, capture_output=True, text=True)
    if r2.returncode != 0:
        raise RuntimeError(
            f"Audio extraction failed for {input_video}\nstderr={r2.stderr}"
        )


def transcribe_with_openrouter(audio_path: Path, model: str = "google/gemini-2.0-flash-lite-001") -> dict:
    """Transcribe audio using OpenRouter API.
    
    Args:
        audio_path: Path to audio file
        model: OpenRouter model name that supports audio input
        
    Returns:
        Full API response as dictionary
    """
    # Read and base64 encode audio
    audio_bytes = audio_path.read_bytes()
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    
    # Determine audio format from file extension
    audio_format = audio_path.suffix.lstrip(".").lower()
    if audio_format == "m4a":
        audio_format = "m4a"
    elif audio_format not in ["wav", "mp3", "aiff", "aac", "ogg", "flac", "m4a"]:
        # Default to m4a if unknown
        audio_format = "m4a"
    
    # Build request payload - try different formats
    # Format 1: Try with input_audio (snake_case) consistently
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Transcribe the following audio as clean verbatim text in Arabic. No timestamps, no speaker labels, keep punctuation and natural phrasing."
                    },
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio_b64,
                            "format": audio_format
                        }
                    }
                ]
            }
        ],
        "stream": False
    }
    
    # Make API request
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/SilenceRemover",  # Optional: for OpenRouter analytics
        "X-Title": "SilenceRemover Test"  # Optional: for OpenRouter analytics
    }
    
    print(f"Sending request to OpenRouter (model: {model})...")
    print(f"Audio file: {audio_path.name} ({len(audio_bytes)} bytes, base64: {len(audio_b64)} chars)")
    
    response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=120)
    response.raise_for_status()
    
    return response.json()


def main():
    """Test OpenRouter transcription on first video in test directory."""
    test_dir = Path("/Users/mahmoud/Desktop/VIDS/raw")
    temp_dir = Path("/Users/mahmoud/Desktop/VIDS/temp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Find first video file
    video_files = sorted([f for f in test_dir.iterdir() if f.suffix == ".mkv"])
    if not video_files:
        print(f"No video files found in {test_dir}", file=sys.stderr)
        sys.exit(1)
    
    test_video = video_files[0]
    print(f"Testing with: {test_video.name}")
    print("=" * 60)
    
    # Extract first minute of audio - try WAV format first (most compatible)
    audio_output = temp_dir / f"{test_video.stem}_1min.wav"
    print(f"\n[1/3] Extracting first minute of audio as WAV...")
    extract_first_minute_audio(test_video, audio_output, format="wav")
    print(f"Audio extracted: {audio_output}")
    
    # Try transcription with cheapest models
    models_to_try = [
        "google/gemini-2.0-flash-lite-001",  # Cheapest option
        "mistralai/voxtral-small-24b-2507",  # Second cheapest
        "google/gemini-2.5-flash-lite",  # Third cheapest
    ]
    
    for model in models_to_try:
        print(f"\n[2/3] Testing transcription with model: {model}")
        print("-" * 60)
        
        try:
            response = transcribe_with_openrouter(audio_output, model=model)
            
            # Save raw response
            raw_response_path = temp_dir / f"{test_video.stem}_openrouter_response.json"
            with open(raw_response_path, "w", encoding="utf-8") as f:
                json.dump(response, f, indent=2, ensure_ascii=False)
            print(f"Raw response saved: {raw_response_path}")
            
            # Extract transcription
            if "choices" in response and len(response["choices"]) > 0:
                content = response["choices"][0]["message"]["content"]
                print(f"\n[3/3] Transcription result:")
                print("=" * 60)
                print(content)
                print("=" * 60)
                
                # Save transcript
                transcript_path = temp_dir / f"{test_video.stem}_openrouter_transcript.txt"
                transcript_path.write_text(content, encoding="utf-8")
                print(f"\nTranscript saved: {transcript_path}")
                
                # Show usage info if available
                if "usage" in response:
                    usage = response["usage"]
                    print(f"\nUsage: {usage}")
                
                break  # Success, no need to try other models
            else:
                print(f"Warning: Unexpected response format: {response}")
                
        except requests.exceptions.HTTPError as e:
            print(f"Error with model {model}: {e}")
            if e.response is not None:
                try:
                    error_detail = e.response.json()
                    print(f"Error details: {json.dumps(error_detail, indent=2)}")
                except:
                    print(f"Error response: {e.response.text}")
            continue
        except Exception as e:
            print(f"Error with model {model}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print("\n" + "=" * 60)
    print("Test complete!")


if __name__ == "__main__":
    main()
