"""Titles package: title generation and honorific enrichment."""

from .openrouter import (
    generate_title_with_openrouter,
    generate_title_from_transcript,
)

__all__ = [
    "generate_title_with_openrouter",
    "generate_title_from_transcript",
]

