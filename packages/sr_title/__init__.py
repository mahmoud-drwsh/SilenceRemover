"""YouTube-style title generation from transcript via OpenRouter."""

from sr_title.api import (
    DEFAULT_MODEL,
    generate_title_from_transcript,
    generate_title_with_openrouter,
)
from sr_title.prompt import (
    TITLE_CANDIDATES_PROMPT_TEMPLATE,
    TITLE_CANDIDATES_SCORE_PROMPT_TEMPLATE,
    TITLE_PROMPT_TEMPLATE,
)

__all__ = [
    "DEFAULT_MODEL",
    "TITLE_CANDIDATES_PROMPT_TEMPLATE",
    "TITLE_CANDIDATES_SCORE_PROMPT_TEMPLATE",
    "TITLE_PROMPT_TEMPLATE",
    "generate_title_from_transcript",
    "generate_title_with_openrouter",
]
