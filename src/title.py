"""Title generation from transcript using OpenRouter (title step then honorific step)."""

import sys
from pathlib import Path

from src.config import (
    ADD_HONORIFIC_PROMPT_TEMPLATE,
    OPENROUTER_TITLE_MODEL,
    TITLE_PROMPT_TEMPLATE,
)
from src.openrouter_client import request as openrouter_request


def _first_line(text: str) -> str:
    """Extract first non-empty line from response text."""
    return (text.strip().splitlines() or [""])[0]


def generate_title_with_openrouter(
    api_key: str, transcript: str, log_dir: Path | None = None
) -> str:
    """Generate title from transcript using OpenRouter API (two steps: title then honorific).

    Args:
        api_key: OpenRouter API key
        transcript: Transcript text
        log_dir: If set, log request/response to log_dir/openrouter_requests.log

    Returns:
        Generated title with honorifics (single line)
    """
    # Step 1: Generate title from transcript (no honorific rules)
    prompt1 = TITLE_PROMPT_TEMPLATE.format(transcript=transcript)
    messages1 = [
        {"role": "user", "content": [{"type": "text", "text": prompt1}]},
    ]
    print(f"Generating title with model: {OPENROUTER_TITLE_MODEL}")
    raw_title = openrouter_request(
        api_key, OPENROUTER_TITLE_MODEL, messages1, log_dir=log_dir
    )
    raw_title = _first_line(raw_title)
    if not raw_title:
        raise RuntimeError("Title generation returned empty response")

    # Step 2: Add honorifics (سيدنا before محمد, ﷺ after Prophet mentions); idempotent
    # On empty response or exception, fall back to raw title
    try:
        prompt2 = ADD_HONORIFIC_PROMPT_TEMPLATE.format(title=raw_title)
        messages2 = [
            {"role": "user", "content": [{"type": "text", "text": prompt2}]},
        ]
        print("Adding honorific to title...")
        title_text = openrouter_request(
            api_key, OPENROUTER_TITLE_MODEL, messages2, log_dir=log_dir
        )
        title_text = _first_line(title_text)
    except Exception as e:
        print(f"Honorific step failed ({e}), using original title.", file=sys.stderr)
        return raw_title
    if not title_text:
        print("Honorific step returned empty response, using original title.", file=sys.stderr)
        return raw_title
    return title_text


def generate_title_from_transcript(
    api_key: str,
    transcript_path: Path,
    output_path: Path,
    log_dir: Path | None = None,
) -> None:
    """Generate title from transcript file and save to output file.

    Args:
        api_key: OpenRouter API key
        transcript_path: Path to transcript text file
        output_path: Path to save title text file
        log_dir: If set, log request/response to log_dir/openrouter_requests.log
    """
    print(f"Reading transcript from: {transcript_path}")
    transcript = transcript_path.read_text(encoding="utf-8")
    title_text = generate_title_with_openrouter(api_key, transcript, log_dir)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(title_text, encoding="utf-8")
    print(f"Title saved to: {output_path}")
