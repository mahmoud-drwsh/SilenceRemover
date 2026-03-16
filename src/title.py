"""Backward-compatibility shim for title generation.

The actual implementations now live in `src.titles.openrouter`, but this module
keeps the old import paths working.
"""

from pathlib import Path

from src.titles.openrouter import (
    generate_title_with_openrouter,
    generate_title_from_transcript,
)

__all__ = [
    "generate_title_with_openrouter",
    "generate_title_from_transcript",
]
