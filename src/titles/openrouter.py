"""Title generation from transcript using OpenRouter (title step then honorific step)."""

import re
import sys
from pathlib import Path
from src.prompts import (
    ADD_HONORIFIC_PROMPT_TEMPLATE,
    TITLE_PROMPT_TEMPLATE,
)
from src.openrouter_client import request as openrouter_request


def _first_line(text: str) -> str:
    """Extract first non-empty line from response text."""
    return (text.strip().splitlines() or [""])[0]


_PROPHET_TERMS = [
    "محمد",
    "رسول الله",
    "النبي",
    "المصطفى",
]


def _normalize_honorifics(title: str) -> str:
    """Best-effort normalization for common LLM honorific mistakes.

    - Collapses repeated ﷺ tokens.
    - Avoids patterns like: "النبي ﷺ المصطفى ﷺ" -> "النبي المصطفى ﷺ"
      (single honorific at the end of consecutive Prophet epithets).
    """
    text = (title or "").strip()
    if not text:
        return text

    # Collapse consecutive/repeated honorific tokens.
    text = re.sub(r"(?:\s*ﷺ){2,}", " ﷺ", text)

    # If two Prophet terms appear consecutively and both got ﷺ, keep only the last one.
    # Example: "النبي ﷺ المصطفى ﷺ" -> "النبي المصطفى ﷺ"
    terms_alt = "|".join(map(re.escape, _PROPHET_TERMS))
    text = re.sub(
        rf"(\b(?:{terms_alt})\b)\s*ﷺ(\s+)(?=(?:{terms_alt})\b)",
        r"\1\2",
        text,
    )

    # Tidy spaces around the honorific.
    text = re.sub(r"\s+ﷺ", " ﷺ", text)
    text = re.sub(r"ﷺ\s+", "ﷺ ", text)
    return text.strip()


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
    print("Generating title with model: google/gemini-2.5-flash-lite:nitro")
    raw_title = openrouter_request(
        api_key, "google/gemini-2.5-flash-lite:nitro", messages1, log_dir=log_dir
    )
    raw_title = _first_line(str(raw_title))
    if not raw_title:
        # Log and signal failure so the caller can skip this item.
        print("Title generation returned empty response.", file=sys.stderr)
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
            api_key, "google/gemini-2.5-flash-lite:nitro", messages2, log_dir=log_dir
        )
        title_text = _normalize_honorifics(_first_line(title_text))
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


__all__ = [
    "generate_title_with_openrouter",
    "generate_title_from_transcript",
]

