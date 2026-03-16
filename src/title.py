"""Title generation from transcript using OpenRouter."""

from src.config import OPENROUTER_TITLE_MODEL, TITLE_PROMPT_TEMPLATE
from src.openrouter_client import request as openrouter_request


def generate_title_with_openrouter(api_key: str, transcript: str) -> str:
    """Generate title from transcript using OpenRouter API.

    Args:
        api_key: OpenRouter API key
        transcript: Transcript text

    Returns:
        Generated title (single line)
    """
    prompt = TITLE_PROMPT_TEMPLATE.format(transcript=transcript)

    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": prompt}],
        }
    ]

    print(f"Generating title with model: {OPENROUTER_TITLE_MODEL}")
    title = openrouter_request(api_key, OPENROUTER_TITLE_MODEL, messages)
    title_text = (title.strip().splitlines() or [""])[0]

    if not title_text:
        raise RuntimeError("Title generation returned empty response")

    return title_text
