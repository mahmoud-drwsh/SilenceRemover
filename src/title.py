"""Title generation from transcript using OpenRouter (title step then honorific step)."""

from src.config import (
    ADD_HONORIFIC_PROMPT_TEMPLATE,
    OPENROUTER_TITLE_MODEL,
    TITLE_PROMPT_TEMPLATE,
)
from src.openrouter_client import request as openrouter_request


def _first_line(text: str) -> str:
    """Extract first non-empty line from response text."""
    return (text.strip().splitlines() or [""])[0]


def generate_title_with_openrouter(api_key: str, transcript: str) -> str:
    """Generate title from transcript using OpenRouter API (two steps: title then honorific).

    Args:
        api_key: OpenRouter API key
        transcript: Transcript text

    Returns:
        Generated title with honorifics (single line)
    """
    # Step 1: Generate title from transcript (no honorific rules)
    prompt1 = TITLE_PROMPT_TEMPLATE.format(transcript=transcript)
    messages1 = [
        {"role": "user", "content": [{"type": "text", "text": prompt1}]},
    ]
    print(f"Generating title with model: {OPENROUTER_TITLE_MODEL}")
    raw_title = openrouter_request(api_key, OPENROUTER_TITLE_MODEL, messages1)
    raw_title = _first_line(raw_title)
    if not raw_title:
        raise RuntimeError("Title generation returned empty response")

    # Step 2: Add honorifics (سيدنا before محمد, ﷺ after Prophet mentions); idempotent
    prompt2 = ADD_HONORIFIC_PROMPT_TEMPLATE.format(title=raw_title)
    messages2 = [
        {"role": "user", "content": [{"type": "text", "text": prompt2}]},
    ]
    print("Adding honorific to title...")
    title_text = openrouter_request(api_key, OPENROUTER_TITLE_MODEL, messages2)
    title_text = _first_line(title_text)
    if not title_text:
        raise RuntimeError("Honorific step returned empty response")

    return title_text
