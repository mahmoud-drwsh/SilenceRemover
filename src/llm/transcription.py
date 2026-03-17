"""Video transcription: audio extraction and OpenRouter transcription."""

import base64
from pathlib import Path

from src.core.constants import AUDIO_EXTENSIONS, AUDIO_FILE_EXT, AUDIO_FORMATS
from src.llm.prompts import TRANSCRIBE_PROMPT
from src.ffmpeg.core import print_ffmpeg_cmd
from src.ffmpeg.runner import run
from src.ffmpeg.transcode import (
    build_first_5min_audio_aac_command,
    build_first_5min_audio_copy_command,
    build_first_5min_audio_ogg_command,
    build_first_5min_audio_wav_command,
)
from src.llm.client import request as openrouter_request


def extract_first_5min_audio(input_video: Path, output_audio: Path, format: str = "ogg") -> None:
    """Extract first 5 minutes of audio from video.

    Args:
        input_video: Input video file
        output_audio: Output audio file path
        format: Audio format (wav, m4a, ogg, etc.). Defaults to ogg.
    """
    output_audio.parent.mkdir(parents=True, exist_ok=True)

    if format == "wav":
        # Extract as WAV format (16kHz mono)
        cmd = build_first_5min_audio_wav_command(input_video=input_video, output_audio=output_audio)
        print_ffmpeg_cmd(cmd)
        result = run(cmd, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Audio extraction failed for {input_video}\nstderr={result.stderr}"
            )
    elif format == "ogg":
        # OGG/Opus: smaller payload for transcription (same token cost, less bandwidth)
        cmd = build_first_5min_audio_ogg_command(input_video=input_video, output_audio=output_audio)
        print_ffmpeg_cmd(cmd)
        result = run(cmd, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Audio extraction failed for {input_video}\nstderr={result.stderr}"
            )
    else:
        # Try to copy audio stream first
        copy_cmd = build_first_5min_audio_copy_command(input_video=input_video, output_audio=output_audio)
        print_ffmpeg_cmd(copy_cmd)
        copy_result = run(copy_cmd, capture_output=True, check=False)
        if copy_result.returncode == 0:
            return
        # Fallback: encode to aac
        enc_cmd = build_first_5min_audio_aac_command(input_video=input_video, output_audio=output_audio)
        print_ffmpeg_cmd(enc_cmd)
        encode_result = run(enc_cmd, capture_output=True, check=False)
        if encode_result.returncode != 0:
            raise RuntimeError(
                "Audio extraction failed for "
                f"{input_video}\ncopy_stderr={copy_result.stderr}\nenc_stderr={encode_result.stderr}"
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
    if media_path.suffix.lower() in AUDIO_EXTENSIONS:
        print(f"Using audio directly (no extraction): {media_path.name}")
        return media_path.resolve()
    audio_path = temp_dir / f"{basename}{AUDIO_FILE_EXT}"
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
    if audio_format not in AUDIO_FORMATS:
        supported = ", ".join(sorted(AUDIO_FORMATS))
        raise ValueError(f"Unsupported audio format: {audio_format}. Supported: {supported}")

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
