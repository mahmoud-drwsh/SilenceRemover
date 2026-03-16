"""Transcription package: audio extraction and OpenRouter transcription."""

from .openrouter import (
    extract_first_5min_audio,
    get_audio_path_for_media,
    transcribe_with_openrouter,
    transcribe_and_save,
)

__all__ = [
    "extract_first_5min_audio",
    "get_audio_path_for_media",
    "transcribe_with_openrouter",
    "transcribe_and_save",
]

