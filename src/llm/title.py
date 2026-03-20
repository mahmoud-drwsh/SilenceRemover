"""Title generation from transcript using OpenRouter (title step then honorific step)."""

import re
import sys
from pathlib import Path

from src.llm.prompts import (
    HONORIFIC_APPLY_PROMPT_TEMPLATE,
    HONORIFIC_CHECK_PROMPT_TEMPLATE,
    TITLE_PROMPT_TEMPLATE,
    TITLE_VERBATIM_CHECK_PROMPT_TEMPLATE,
)
from src.llm.client import request as openrouter_request


def _first_line(text: str) -> str:
    """Extract first non-empty line from response text."""
    return (text.strip().splitlines() or [""])[0]


def _single_non_empty_line(text: str) -> str:
    """Return a single non-empty line only; otherwise return an empty string."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) != 1:
        return ""
    return lines[0]


def _parse_honorific_check(raw_response: str) -> bool | None:
    """Parse strict YES/NO output from honorific-check model step."""
    response = _single_non_empty_line(raw_response).upper()
    if response == "YES":
        return True
    if response == "NO":
        return False
    return None


def _parse_yes_no(raw_response: str) -> bool | None:
    """Parse strict YES/NO output from a model step."""
    response = _single_non_empty_line(raw_response).upper()
    if not response:
        return None
    # Allow trailing punctuation like YES. / NO!
    response = re.sub(r"[.!?]+$", "", response).strip()
    if response == "YES":
        return True
    if response == "NO":
        return False
    return None


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

    # If the title already contains "عليه الصلاة والسلام"/"عليه السلام",
    # then a following standalone "ﷺ" is typically redundant—remove it deterministically.
    text = re.sub(
        r"(عليه\s+الصلاة\s+والسلام|عليه\s+السلام)\s*ﷺ+",
        r"\1",
        text,
    )

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
    # Step 1: Generate base title (verbatim) with up to 3 retries + verifier gate.
    prompt1 = TITLE_PROMPT_TEMPLATE.format(transcript=transcript)
    messages1 = [
        {"role": "user", "content": [{"type": "text", "text": prompt1}]},
    ]
    verifier_model = "google/gemini-2.5-flash-lite:nitro"

    raw_title: str = ""
    last_candidate: str = ""
    for attempt in range(1, 4):
        print(
            f"Generating base title (attempt {attempt}/3) with model: {verifier_model}"
        )
        candidate = openrouter_request(
            api_key, verifier_model, messages1, log_dir=log_dir
        )
        candidate = _first_line(str(candidate)).strip()
        if not candidate:
            print("Title generation returned empty response; retrying...", file=sys.stderr)
            continue

        # Verify the candidate is verbatim from the transcript.
        verify_prompt = TITLE_VERBATIM_CHECK_PROMPT_TEMPLATE.format(
            transcript=transcript, candidate_title=candidate
        )
        verify_messages = [
            {"role": "user", "content": [{"type": "text", "text": verify_prompt}]}
        ]
        print("Verifying candidate is verbatim from transcript...")
        verify_response = openrouter_request(
            api_key, verifier_model, verify_messages, log_dir=log_dir
        )
        is_verbatim = _parse_yes_no(str(verify_response))
        if is_verbatim is True:
            raw_title = candidate
            break

        last_candidate = candidate
        print(
            "Verbatim verification rejected the candidate; retrying...",
            file=sys.stderr,
        )

    if not raw_title:
        if last_candidate:
            print(
                "Verbatim verification rejected all candidates; proceeding with last candidate.",
                file=sys.stderr,
            )
            raw_title = last_candidate
        else:
            raw_title = ""
    if not raw_title:
        # Log and signal failure so the caller can skip this item.
        print("Title generation returned empty response after retries.", file=sys.stderr)
        raise RuntimeError("Title generation returned empty response")

    try:
        # Step 2: Check whether honorific edits are needed.
        check_prompt = HONORIFIC_CHECK_PROMPT_TEMPLATE.format(title=raw_title)
        check_messages = [
            {"role": "user", "content": [{"type": "text", "text": check_prompt}]},
        ]
        print("Checking whether honorifics are needed...")
        check_response = openrouter_request(
            api_key,
            "google/gemini-2.5-flash-lite:nitro",
            check_messages,
            log_dir=log_dir,
        )
        needs_honorific = _parse_honorific_check(str(check_response))
        if needs_honorific is None:
            print(
                "Honorific check returned non-binary response; using original title.",
                file=sys.stderr,
            )
            return raw_title
        if not needs_honorific:
            return raw_title

        # Step 3: Apply only honorific edits when needed.
        apply_prompt = HONORIFIC_APPLY_PROMPT_TEMPLATE.format(title=raw_title)
        messages2 = [
            {"role": "user", "content": [{"type": "text", "text": apply_prompt}]},
        ]
        print("Adding honorific to title...")
        title_response = openrouter_request(
            api_key, "google/gemini-2.5-flash-lite:nitro", messages2, log_dir=log_dir
        )
        title_text = _normalize_honorifics(_single_non_empty_line(str(title_response)))
        if not title_text:
            print(
                "Honorific apply returned invalid response, using original title.",
                file=sys.stderr,
            )
            return raw_title
    except Exception as e:
        print(f"Honorific pipeline failed ({e}), using original title.", file=sys.stderr)
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
    transcript = transcript_path.read_text(encoding="utf-8").strip()
    # Use the full transcript for the title step; the prompt instructs the model
    # to extract from the early speech portion of the transcript.
    title_text = generate_title_with_openrouter(api_key, transcript, log_dir)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(title_text, encoding="utf-8")
    print(f"Title saved to: {output_path}")


__all__ = [
    "generate_title_with_openrouter",
    "generate_title_from_transcript",
]
