"""Title generation from transcript using OpenRouter."""

import json
import re
import sys
from pathlib import Path

from src.llm.prompts import (
    TITLE_CANDIDATES_PROMPT_TEMPLATE,
    TITLE_VERBATIM_CHECK_PROMPT_TEMPLATE,
)
from src.llm.client import request as openrouter_request


def _single_non_empty_line(text: str) -> str:
    """Return a single non-empty line only; otherwise return an empty string."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) != 1:
        return ""
    return lines[0]


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
_TITLE_LENGTH_IDEAL_MIN = 20
_TITLE_LENGTH_IDEAL_MAX = 80


def _strip_optional_json_fences(text: str) -> str:
    """Remove leading/trailing ```json / ``` fences if the model added them."""
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if not lines:
        return t
    if lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_title_candidates_json(raw: str, expected: int) -> list[str]:
    """Parse a JSON array of single-line title strings; dedupe; require at least one."""
    text = _strip_optional_json_fences(raw.strip())
    data: object
    try:
        data = json.loads(text)
    except json.JSONDecodeError as first_err:
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError(
                "Title batch generation returned no parseable JSON array"
            ) from first_err
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Title batch JSON parse failed: {e}") from e

    if not isinstance(data, list):
        raise RuntimeError("Title batch JSON must be a JSON array of strings")

    out: list[str] = []
    seen: set[str] = set()
    for i, item in enumerate(data):
        if not isinstance(item, str):
            raise RuntimeError(
                f"Title batch JSON array element {i} is not a string"
            )
        s = item.strip()
        if not s:
            continue
        if "\n" in s or "\r" in s:
            raise RuntimeError(
                f"Title batch candidate {i} contains a newline; each title must be one line"
            )
        if s in seen:
            continue
        seen.add(s)
        out.append(s)

    if not out:
        raise RuntimeError("Title batch JSON contained no non-empty title strings")

    if len(out) < expected:
        print(
            f"Title batch returned {len(out)} unique candidate(s); expected {expected}. "
            "Proceeding with available candidates.",
            file=sys.stderr,
        )
    elif len(out) > expected:
        print(
            f"Title batch returned {len(out)} unique candidates; using first {expected} only.",
            file=sys.stderr,
        )
        out = out[:expected]
    return out


def _generate_title_candidates(
    api_key: str,
    verifier_model: str,
    transcript: str,
    *,
    target_count: int = _TITLE_CANDIDATE_TARGET_COUNT,
    log_dir: Path | None = None,
) -> list[str]:
    """Generate unique single-line title candidates in one model call (JSON array)."""
    prompt = TITLE_CANDIDATES_PROMPT_TEMPLATE.format(
        transcript=transcript,
        candidate_count=target_count,
    )
    messages = [
        {"role": "user", "content": [{"type": "text", "text": prompt}]},
    ]
    print(
        f"Generating {target_count} title candidates in one call with model: {verifier_model}"
    )
    raw = openrouter_request(api_key, verifier_model, messages, log_dir=log_dir)
    return _parse_title_candidates_json(str(raw), expected=target_count)


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


def generate_title_with_openrouter(
    api_key: str, transcript: str, log_dir: Path | None = None
) -> str:
    """Generate title from transcript using OpenRouter (candidate pool, verify, select).

    Args:
        api_key: OpenRouter API key
        transcript: Transcript text
        log_dir: If set, log request/response to log_dir/openrouter_requests.log

    Returns:
        Selected title text (single line)
    """
    # Use one shared transcript payload for generation and verifier prompts.
    # The templates enforce beginning-only extraction from opening complete sentences.
    title_source_transcript = transcript.strip()

    verifier_model = "google/gemini-3.1-flash-lite-preview"

    # Phase 1: one generation call for the candidate pool, then verify all, then pick best.
    try:
        candidates = _generate_title_candidates(
            api_key,
            verifier_model,
            title_source_transcript,
            target_count=_TITLE_CANDIDATE_TARGET_COUNT,
            log_dir=log_dir,
        )
    except RuntimeError as e:
        print(f"Title batch generation failed: {e}", file=sys.stderr)
        raise
    if not candidates:
        print(
            "Title generation produced no usable candidates.",
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

    return raw_title


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
