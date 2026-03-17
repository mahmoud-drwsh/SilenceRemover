"""LLM domain package for transcription and title generation."""

from src.llm.client import request
from src.llm.prompts import ADD_HONORIFIC_PROMPT_TEMPLATE, TITLE_PROMPT_TEMPLATE, TRANSCRIBE_PROMPT
from src.llm.title import generate_title_from_transcript, generate_title_with_openrouter
from src.llm.transcription import (
    extract_first_5min_audio,
    get_audio_path_for_media,
    transcribe_and_save,
    transcribe_with_openrouter,
)

__all__ = [
    "request",
    "ADD_HONORIFIC_PROMPT_TEMPLATE",
    "TITLE_PROMPT_TEMPLATE",
    "TRANSCRIBE_PROMPT",
    "generate_title_from_transcript",
    "generate_title_with_openrouter",
    "extract_first_5min_audio",
    "get_audio_path_for_media",
    "transcribe_and_save",
    "transcribe_with_openrouter",
]
