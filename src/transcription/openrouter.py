"""Video transcription: audio extraction and OpenRouter transcription."""

import base64
import subprocess
from pathlib import Path

from src.config import AUDIO_BITRATE
from src.prompts import TRANSCRIBE_PROMPT
from src.ffmpeg_utils import build_ffmpeg_cmd, print_ffmpeg_cmd
from src.openrouter_client import request as openrouter_request

_AUDIO_EXTENSIONS = {".wav", ".m4a", ".mp3", ".aac", ".ogg", ".flac", ".aiff"}


def extract_first_5min_audio(input_video: Path, output_audio: Path, format: str = "wav") -> None:
    """Extract first 5 minutes of audio from video.

    Args:
        input_video: Input video file
        output_audio: Output audio file path
        format: Audio format (wav, m4a, etc.). Defaults to wav for better compatibility.
    """
    output_audio.parent.mkdir(parents=True, exist_ok=True)

    if format == "wav":
        # Extract as WAV format (16kHz mono)
        enc_cmd = build_ffmpeg_cmd(overwrite=True)
        enc_cmd.extend([
            "-ss", "0", "-t", "300",  # First 5 minutes
            "-i", str(input_video),
            "-map", "0:a:0", "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", "-vn",
            str(output_audio),
        ])
        print_ffmpeg_cmd(enc_cmd)
        r = subprocess.run(enc_cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(
                f"Audio extraction failed for {input_video}\nstderr={r.stderr}"
            )
    elif format == "ogg":
        # OGG/Opus: smaller payload for transcription (same token cost, less bandwidth)
        enc_cmd = build_ffmpeg_cmd(overwrite=True)
        enc_cmd.extend([
            "-ss", "0", "-t", "300",
            "-i", str(input_video),
            "-map", "0:a:0", "-c:a", "libopus", "-ar", "16000", "-ac", "1", "-b:a", "32k", "-vn",
            str(output_audio),
        ])
        print_ffmpeg_cmd(enc_cmd)
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
        print_ffmpeg_cmd(copy_cmd)
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
        print_ffmpeg_cmd(enc_cmd)
        r2 = subprocess.run(enc_cmd, capture_output=True, text=True)
        if r2.returncode != 0:
            raise RuntimeError(
                f"Audio extraction failed for {input_video}\ncopy_stderr={r.stderr}\nenc_stderr={r2.stderr}"
            )


def get_audio_path_for_media(media_path: Path, temp_dir: Path, basename: str) -> Path:
    """Resolve audio path for transcription: use media_path if audio, else extract first 5 min to temp_dir.

    Args:
        media_path: Video or audio file path
        temp_dir: Directory for extracted audio when media_path is video
        basename: Base name for extracted file (e.g. stem of video)

    Returns:
        Path to audio file to transcribe
    """
    if media_path.suffix.lower() in _AUDIO_EXTENSIONS:
        print(f"Using audio directly (no extraction): {media_path.name}")
        return media_path.resolve()
    audio_path = temp_dir / f"{basename}.ogg"
    if not audio_path.exists():
        print(f"Extracting audio (5 min) -> {audio_path}")
        extract_first_5min_audio(media_path, audio_path, format="ogg")
    else:
        print("Audio already exists (skipping extraction).")
    return audio_path


def transcribe_with_openrouter(
    api_key: str,
    audio_path: Path,
    model: str = "google/gemini-2.5-flash-lite:nitro",
    log_dir: Path | None = None,
) -> str:
    """Transcribe audio using OpenRouter API.

    Args:
        api_key: OpenRouter API key
        audio_path: Path to audio file
        model: OpenRouter model name that supports audio input
        log_dir: If set, log request/response to log_dir/openrouter_requests.log

    Returns:
        Transcript text
    """
    audio_bytes = audio_path.read_bytes()
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    audio_format = audio_path.suffix.lstrip(".").lower()
    if audio_format not in ["wav", "mp3", "aiff", "aac", "ogg", "flac", "m4a"]:
        audio_format = "wav"

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": TRANSCRIBE_PROMPT},
                {
                    "type": "input_audio",
                    "input_audio": {"data": audio_b64, "format": audio_format},
                },
            ],
        }
    ]

    return openrouter_request(api_key, model, messages, log_dir=log_dir)


def transcribe_and_save(
    api_key: str,
    audio_path: Path,
    output_path: Path,
    model: str = "google/gemini-2.5-flash-lite:nitro",
    log_dir: Path | None = None,
) -> None:
    """Transcribe audio and save transcript to file.

    Args:
        api_key: OpenRouter API key
        audio_path: Path to audio file
        output_path: Path to save transcript text file
        model: OpenRouter model name that supports audio input
        log_dir: If set, log request/response to log_dir/openrouter_requests.log
    """
    print(f"Transcribing audio: {audio_path.name}")
    transcript_text = transcribe_with_openrouter(api_key, audio_path, model, log_dir)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(transcript_text, encoding="utf-8")
    print(f"Transcript saved to: {output_path}")


__all__ = [
    "extract_first_5min_audio",
    "get_audio_path_for_media",
    "transcribe_with_openrouter",
    "transcribe_and_save",
]

