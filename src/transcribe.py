"""Video transcription and title generation functionality."""

import base64
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: requests library not installed. Install 'requests' to use transcribe/title.", file=sys.stderr)
    sys.exit(1)

from src.main_utils import (
    AUDIO_BITRATE,
    OPENROUTER_API_URL,
    OPENROUTER_DEFAULT_MODEL,
    OPENROUTER_TITLE_MODEL_FREE,
    OPENROUTER_TITLE_MODEL_FREE_FALLBACK,
    OPENROUTER_TITLE_MODEL_PAID,
    TRANSCRIBE_PROMPT,
    TITLE_PROMPT_TEMPLATE,
    build_ffmpeg_cmd,
)


def extract_first_5min_audio(input_video: Path, output_audio: Path, format: str = "wav") -> None:
    """Extract first 5 minutes of audio from video.
    
    Args:
        input_video: Input video file
        output_audio: Output audio file path
        format: Audio format (wav, m4a, etc.). Defaults to wav for better compatibility.
    """
    output_audio.parent.mkdir(parents=True, exist_ok=True)
    
    if format == "wav":
        # Extract as WAV format (16kHz mono for cost efficiency)
        enc_cmd = build_ffmpeg_cmd(overwrite=True)
        enc_cmd.extend([
            "-ss", "0", "-t", "300",  # First 5 minutes
            "-i", str(input_video),
            "-map", "0:a:0", "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", "-vn",
            str(output_audio),
        ])
        r = subprocess.run(enc_cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(
                f"Audio extraction failed for {input_video}\nstderr={r.stderr}"
            )
    else:
        # Try to copy audio stream first
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
        # Fallback: encode to aac
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
    """Parse retry delay from error message."""
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


def _openrouter_request_with_retry(
    api_key: str,
    model: str,
    messages: list[dict],
    raw_response_path: Path | None = None,
    max_attempts: int = 5,
    initial_backoff_sec: float = 1.0,
    max_backoff_sec: float = 30.0,
    multiplier: float = 2.0,
    jitter_ratio: float = 0.2,
) -> str:
    """Make OpenRouter API request with retry logic.
    
    Args:
        api_key: OpenRouter API key
        model: Model name to use
        messages: List of message dictionaries for the API
        raw_response_path: Optional path to save raw JSON response
        max_attempts: Maximum number of retry attempts
        initial_backoff_sec: Initial backoff delay in seconds
        max_backoff_sec: Maximum backoff delay in seconds
        multiplier: Exponential backoff multiplier
        jitter_ratio: Jitter ratio for backoff
        
    Returns:
        Response text content
    """
    attempt = 0
    last_err: Exception | None = None
    
    payload = {
        "model": model,
        "messages": messages,
        "stream": False
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/SilenceRemover",
        "X-Title": "SilenceRemover"
    }
    
    while attempt < max_attempts:
        try:
            response = requests.post(
                OPENROUTER_API_URL,
                headers=headers,
                json=payload,
                timeout=120
            )
            response.raise_for_status()
            
            result = response.json()
            
            # Save raw response if path provided
            if raw_response_path is not None:
                try:
                    raw_response_path.parent.mkdir(parents=True, exist_ok=True)
                    raw_response_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
                except Exception as e:
                    print(f"Warning: Could not save raw response to {raw_response_path}: {e}", file=sys.stderr)
            
            # Extract text from response
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"]
                return content or ""
            else:
                raise ValueError(f"Unexpected response format: {result}")
                
        except KeyboardInterrupt:
            raise
        except requests.exceptions.HTTPError as e:
            last_err = e
            # Check if it's a rate limit error
            if e.response is not None:
                status_code = e.response.status_code
                if status_code == 429:  # Rate limit
                    suggested_delay = _parse_retry_seconds_from_error(e)
                elif status_code >= 500:  # Server error
                    suggested_delay = 5.0
                else:
                    # Client error (4xx) - don't retry
                    raise
            else:
                suggested_delay = 6.0
        except Exception as e:
            last_err = e
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


def transcribe_with_openrouter(api_key: str, audio_path: Path, model: str = OPENROUTER_DEFAULT_MODEL) -> str:
    """Transcribe audio using OpenRouter API.
    
    Args:
        api_key: OpenRouter API key
        audio_path: Path to audio file
        model: OpenRouter model name that supports audio input
        
    Returns:
        Transcript text
    """
    # Read and base64 encode audio
    audio_bytes = audio_path.read_bytes()
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    
    # Determine audio format from file extension
    audio_format = audio_path.suffix.lstrip(".").lower()
    if audio_format not in ["wav", "mp3", "aiff", "aac", "ogg", "flac", "m4a"]:
        audio_format = "wav"  # Default to wav
    
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": TRANSCRIBE_PROMPT
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
    ]
    
    return _openrouter_request_with_retry(api_key, model, messages)


def generate_title_with_openrouter(api_key: str, transcript: str) -> str:
    """Generate title from transcript using OpenRouter API with fallback logic.
    
    Tries free models first, falls back to paid model if free models fail.
    
    Args:
        api_key: OpenRouter API key
        transcript: Transcript text
        
    Returns:
        Generated title
    """
    prompt = TITLE_PROMPT_TEMPLATE.format(transcript=transcript)
    
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt
                }
            ]
        }
    ]
    
    # Try free models first, then fallback to paid
    models_to_try = [
        (OPENROUTER_TITLE_MODEL_FREE, "free"),
        (OPENROUTER_TITLE_MODEL_FREE_FALLBACK, "free fallback"),
        (OPENROUTER_TITLE_MODEL_PAID, "paid fallback"),
    ]
    
    last_error = None
    
    for model, model_type in models_to_try:
        try:
            print(f"Generating title with {model_type} model: {model}")
            title = _openrouter_request_with_retry(api_key, model, messages)
            title_text = (title.strip().splitlines() or [""])[0]
            if title_text:
                if model_type != "free":
                    print(f"Note: Used {model_type} model due to free model unavailability")
                return title_text
            else:
                # Empty response - try next model
                print(f"Warning: Empty response from {model}, trying next model...")
                continue
        except requests.exceptions.HTTPError as e:
            last_error = e
            # Check if it's a retryable error
            if e.response is not None:
                status_code = e.response.status_code
                # Rate limit, quota, or server errors - try next model
                if status_code in (429, 402, 503) or status_code >= 500:
                    print(f"Model {model} failed with status {status_code}, trying next model...")
                    continue
                else:
                    # Client error (4xx) that's not retryable - try next model anyway
                    print(f"Model {model} failed with status {status_code}, trying next model...")
                    continue
            else:
                # No response object - try next model
                print(f"Model {model} failed: {e}, trying next model...")
                continue
        except Exception as e:
            last_error = e
            print(f"Model {model} failed with error: {e}, trying next model...")
            continue
    
    # If all models failed, raise the last error
    if last_error:
        raise RuntimeError(f"All title generation models failed. Last error: {last_error}") from last_error
    else:
        raise RuntimeError("All title generation models returned empty responses")


def transcribe_single_video(trimmed_video: Path, temp_dir: Path, api_key: str, basename: str) -> tuple[Path, Path]:
    """Transcribe a single trimmed video. Returns (transcript_path, title_path). Skips if files exist.
    
    Args:
        trimmed_video: Path to trimmed video file
        temp_dir: Temporary directory for intermediate files
        api_key: OpenRouter API key
        basename: Base name for output files
        
    Returns:
        Tuple of (transcript_path, title_path)
    """
    audio_path = temp_dir / f"{basename}.wav"  # Use WAV format
    transcript_path = temp_dir / f"{basename}.txt"
    title_path = temp_dir / f"{basename}.title.txt"

    if not audio_path.exists():
        print(f"Extracting audio (5 min) -> {audio_path}")
        extract_first_5min_audio(trimmed_video, audio_path, format="wav")
    else:
        print("Audio already exists (skipping extraction).")

    # Check if both transcript and title already exist
    if transcript_path.exists() and title_path.exists():
        print("Transcript and title already exist (skipping).")
        return transcript_path, title_path

    # Always use two separate API calls (transcription first, then title generation)
    # Step 1: Transcription
    if not transcript_path.exists():
        print("Transcribing with OpenRouter...")
        transcript = transcribe_with_openrouter(api_key, audio_path)
        transcript_path.write_text(transcript, encoding="utf-8")
        print(f"Transcript -> {transcript_path}")
    else:
        print("Transcript already exists (skipping).")

    # Step 2: Title generation (with fallback logic)
    if not title_path.exists():
        print("Generating YouTube title...")
        transcript_text = transcript_path.read_text(encoding="utf-8")
        title = generate_title_with_openrouter(api_key, transcript_text)
        title_path.write_text(title, encoding="utf-8")
        print(f"Title -> {title_path}")
    else:
        print("Title already exists (skipping).")

    return transcript_path, title_path
