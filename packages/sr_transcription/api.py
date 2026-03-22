"""Audio transcription API using OpenRouter."""

import base64
from pathlib import Path
from typing import Optional

from openrouter_transport import request as _openrouter_request
from sr_transcription.formats import AUDIO_FORMATS
from sr_transcription.prompt import TRANSCRIBE_PROMPT

DEFAULT_MODEL = "google/gemini-3.1-flash-lite-preview"


def transcribe_with_openrouter(
    api_key: str,
    audio_path: Path,
    model: str = DEFAULT_MODEL,
    log_dir: Path | None = None,
) -> str:
    """Transcribe audio using OpenRouter API.

    Args:
        api_key: OpenRouter API key
        audio_path: Path to audio file
        model: OpenRouter model name that supports audio input
        log_dir: If set, pass through to openrouter_transport (files under log_dir/logs/).

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

    return _openrouter_request(api_key, model, messages, log_dir=log_dir)


def transcribe_and_save(
    api_key: str,
    audio_path: Path,
    output_path: Path,
    model: str = DEFAULT_MODEL,
    log_dir: Path | None = None,
) -> None:
    """Transcribe audio and save transcript to file.

    Args:
        api_key: OpenRouter API key
        audio_path: Path to audio file
        output_path: Path to save transcript text file
        model: OpenRouter model name that supports audio input
        log_dir: If set, pass through to openrouter_transport (files under log_dir/logs/).

    Raises:
        RuntimeError: If the model returns empty or whitespace-only text (nothing is written).
    """
    print(f"Transcribing audio: {audio_path.name}")
    transcript_text = transcribe_with_openrouter(api_key, audio_path, model, log_dir)
    if not transcript_text.strip():
        raise RuntimeError(
            f"Transcription returned empty text for {audio_path.name}; transcript file not written."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(transcript_text, encoding="utf-8")
    print(f"Transcript saved to: {output_path}")


__all__ = ["transcribe_with_openrouter", "transcribe_and_save"]