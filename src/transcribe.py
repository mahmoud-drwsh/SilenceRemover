"""Backward-compatibility shim for transcription functions.

The actual implementations now live in `src.transcription.openrouter`, but this
module keeps the old import paths working.
"""

from pathlib import Path

from src.transcription.openrouter import (
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


# Backward compatibility: re-export so "from src.transcribe import transcribe_single_video" still works
def __getattr__(name: str):
    if name == "transcribe_single_video":
        from src.content import transcribe_single_video
        return transcribe_single_video
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
