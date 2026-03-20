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


# Title candidate pool: generation count and practical length band for ranking.
_TITLE_CANDIDATE_TARGET_COUNT = 3
_TITLE_CANDIDATE_MAX_GENERATION_ATTEMPTS = 8
_TITLE_LENGTH_IDEAL_MIN = 20
_TITLE_LENGTH_IDEAL_MAX = 80


def _sanitize_title_candidate(raw: str) -> str | None:
    """Keep first non-empty line as the title candidate."""
    text = _first_line(str(raw)).strip()
    if not text:
        return None
    return text


def _generate_title_candidates(
    api_key: str,
    verifier_model: str,
    messages: list[dict],
    *,
    target_count: int = _TITLE_CANDIDATE_TARGET_COUNT,
    max_attempts: int = _TITLE_CANDIDATE_MAX_GENERATION_ATTEMPTS,
    log_dir: Path | None = None,
) -> list[str]:
    """Generate up to `target_count` unique single-line title candidates."""
    candidates: list[str] = []
    seen: set[str] = set()
    for attempt in range(1, max_attempts + 1):
        if len(candidates) >= target_count:
            break
        print(
            f"Generating base title candidate ({len(candidates) + 1}/{target_count}, "
            f"draw {attempt}) with model: {verifier_model}"
        )
        raw = openrouter_request(
            api_key, verifier_model, messages, log_dir=log_dir
        )
        candidate = _sanitize_title_candidate(str(raw))
        if not candidate:
            print(
                "Title generation returned empty or invalid multi-line response; retrying...",
                file=sys.stderr,
            )
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        candidates.append(candidate)
    return candidates


def _verify_title_candidate(
    api_key: str,
    verifier_model: str,
    transcript: str,
    candidate: str,
    log_dir: Path | None,
) -> bool:
    """Return True if the verbatim checker accepts the candidate."""
    verify_prompt = TITLE_VERBATIM_CHECK_PROMPT_TEMPLATE.format(
        transcript=transcript, candidate_title=candidate
    )
    verify_messages = [
        {"role": "user", "content": [{"type": "text", "text": verify_prompt}]},
    ]
    print(f"Verifying candidate verbatim: {candidate[:60]!r}...")
    verify_response = openrouter_request(
        api_key, verifier_model, verify_messages, log_dir=log_dir
    )
    return _parse_yes_no(str(verify_response)) is True


def _selection_sort_key(
    transcript: str, candidate: str, generation_index: int
) -> tuple[int, int, int]:
    """Lower tuple is better: earliest match, then length near ideal band, then earlier generation."""
    pos = transcript.find(candidate) if candidate else -1
    pos_key = pos if pos >= 0 else 10**9
    length = len(candidate)
    if length < _TITLE_LENGTH_IDEAL_MIN:
        len_penalty = _TITLE_LENGTH_IDEAL_MIN - length
    elif length > _TITLE_LENGTH_IDEAL_MAX:
        len_penalty = length - _TITLE_LENGTH_IDEAL_MAX
    else:
        len_penalty = 0
    return (pos_key, len_penalty, generation_index)


def _choose_best_title(
    transcript: str,
    candidates: list[str],
    verified_mask: list[bool],
) -> tuple[str, bool]:
    """Pick best title among verified candidates; if none verified, pick best unverified with warning.

    Returns:
        (chosen_title, used_verified_candidate)
    """
    verified_pairs: list[tuple[str, int]] = [
        (c, i) for i, c in enumerate(candidates) if verified_mask[i]
    ]
    if verified_pairs:
        best_c, best_i = min(
            verified_pairs,
            key=lambda pair: _selection_sort_key(transcript, pair[0], pair[1]),
        )
        return best_c, True

    if candidates:
        print(
            "No candidate passed verbatim verification; using deterministic fallback "
            "among generated candidates.",
            file=sys.stderr,
        )
        best_c, best_i = min(
            [(c, i) for i, c in enumerate(candidates)],
            key=lambda pair: _selection_sort_key(transcript, pair[0], pair[1]),
        )
        return best_c, False

    return "", False


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
    # Use one shared transcript payload for generation and verifier prompts.
    # The templates enforce beginning-only extraction from opening complete sentences.
    title_source_transcript = transcript.strip()

    prompt1 = TITLE_PROMPT_TEMPLATE.format(transcript=title_source_transcript)
    messages1 = [
        {"role": "user", "content": [{"type": "text", "text": prompt1}]},
    ]
    verifier_model = "google/gemini-3.1-flash-lite-preview"

    # Phase 1: build a small candidate pool, then verify all, then pick best.
    candidates = _generate_title_candidates(
        api_key,
        verifier_model,
        messages1,
        target_count=_TITLE_CANDIDATE_TARGET_COUNT,
        max_attempts=_TITLE_CANDIDATE_MAX_GENERATION_ATTEMPTS,
        log_dir=log_dir,
    )
    if not candidates:
        print(
            "Title generation produced no usable candidates after attempts.",
            file=sys.stderr,
        )
        raise RuntimeError("Title generation returned empty response")

    verified_mask: list[bool] = []
    for candidate in candidates:
        ok = _verify_title_candidate(
            api_key,
            verifier_model,
            title_source_transcript,
            candidate,
            log_dir,
        )
        verified_mask.append(ok)
        if not ok:
            print(
                "Verbatim verification rejected a candidate; continuing pool check...",
                file=sys.stderr,
            )

    raw_title, used_verified = _choose_best_title(
        title_source_transcript, candidates, verified_mask
    )
    if used_verified:
        print("Selected best verified title from candidate pool.")
    else:
        print(
            "Proceeding with deterministic fallback title (no verified candidate).",
            file=sys.stderr,
        )

    if not raw_title:
        print("Title selection produced empty result.", file=sys.stderr)
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
            "google/gemini-3.1-flash-lite-preview",
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
            api_key, "google/gemini-3.1-flash-lite-preview", messages2, log_dir=log_dir
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
