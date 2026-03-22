"""LLM domain package for transcription and title generation."""

from openrouter_transport import request
from src.llm.audio_for_llm import extract_first_5min_audio, get_audio_path_for_media
from src.llm.prompts import (
    TITLE_CANDIDATES_PROMPT_TEMPLATE,
    TITLE_CANDIDATES_SCORE_PROMPT_TEMPLATE,
    TITLE_PROMPT_TEMPLATE,
)
from src.llm.title import generate_title_from_transcript, generate_title_with_openrouter
from sr_transcription import TRANSCRIBE_PROMPT, transcribe_and_save, transcribe_with_openrouter

__all__ = [
    "request",
    "TITLE_PROMPT_TEMPLATE",
    "TITLE_CANDIDATES_PROMPT_TEMPLATE",
    "TITLE_CANDIDATES_SCORE_PROMPT_TEMPLATE",
    "TRANSCRIBE_PROMPT",
    "generate_title_from_transcript",
    "generate_title_with_openrouter",
    "extract_first_5min_audio",
    "get_audio_path_for_media",
    "transcribe_and_save",
    "transcribe_with_openrouter",
]
