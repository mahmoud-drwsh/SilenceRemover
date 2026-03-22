"""Audio transcription package using OpenRouter."""

from sr_transcription.api import (
    DEFAULT_MODEL,
    transcribe_and_save,
    transcribe_with_openrouter,
)
from sr_transcription.prompt import TRANSCRIBE_PROMPT

__all__ = [
    "DEFAULT_MODEL",
    "transcribe_and_save",
    "transcribe_with_openrouter",
    "TRANSCRIBE_PROMPT",
]
