"""Title generation from transcript using OpenRouter."""

import json
import sys
from pathlib import Path

from openrouter_transport import request as openrouter_request
from src.core.constants import OPENROUTER_DEFAULT_MODEL
from sr_title.prompt import (
    TITLE_CANDIDATES_PROMPT_TEMPLATE,
    TITLE_CANDIDATES_SCORE_PROMPT_TEMPLATE,
)

DEFAULT_MODEL = OPENROUTER_DEFAULT_MODEL

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


def _coerce_score_0_10(field: str, index: int, value: object) -> int:
    """Validate and return an integer score in 0..10."""
    n: int
    if isinstance(value, bool):
        raise RuntimeError(
            f"evaluation[{index}].{field}: boolean is not a valid score"
        )
    if isinstance(value, int):
        n = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise RuntimeError(
                f"evaluation[{index}].{field}: expected integer score, got {value!r}"
            )
        n = int(value)
    else:
        raise RuntimeError(
            f"evaluation[{index}].{field}: expected number, got {type(value).__name__}"
        )
    if not 0 <= n <= 10:
        raise RuntimeError(
            f"evaluation[{index}].{field}: score {n} out of allowed 0..10 range"
        )
    return n


def _parse_title_evaluation_json(raw: str, n: int) -> list[tuple[int, int]]:
    """Parse evaluations JSON object; return list of (verbatim_score, correctness_score)."""
    text = _strip_optional_json_fences(raw.strip())
    data: object
    try:
        data = json.loads(text)
    except json.JSONDecodeError as first_err:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError(
                "Title scoring returned no parseable JSON object"
            ) from first_err
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Title scoring JSON parse failed: {e}") from e

    if not isinstance(data, dict):
        raise RuntimeError("Title scoring JSON must be a JSON object")

    evaluations = data.get("evaluations")
    if not isinstance(evaluations, list):
        raise RuntimeError('Title scoring JSON must contain an "evaluations" array')

    if len(evaluations) != n:
        raise RuntimeError(
            f"Title scoring expected {n} evaluations, got {len(evaluations)}"
        )

    out: list[tuple[int, int]] = []
    for i, item in enumerate(evaluations):
        if not isinstance(item, dict):
            raise RuntimeError(f"evaluation[{i}] must be a JSON object")
        if "verbatim_score" not in item or "correctness_score" not in item:
            raise RuntimeError(
                f"evaluation[{i}] must include verbatim_score and correctness_score"
            )
        v = _coerce_score_0_10("verbatim_score", i, item["verbatim_score"])
        c = _coerce_score_0_10("correctness_score", i, item["correctness_score"])
        out.append((v, c))
    return out


def _evaluate_title_candidates(
    api_key: str,
    model: str,
    transcript: str,
    candidates: list[str],
    log_dir: Path | None,
) -> list[tuple[int, int]]:
    """One model call: score all candidates (verbatim + correctness)."""
    candidates_json = json.dumps(candidates, ensure_ascii=False)
    prompt = TITLE_CANDIDATES_SCORE_PROMPT_TEMPLATE.format(
        transcript=transcript,
        candidates_json=candidates_json,
    )
    messages = [
        {"role": "user", "content": [{"type": "text", "text": prompt}]},
    ]
    print(
        f"Scoring {len(candidates)} title candidates in one call with model: {model}"
    )
    raw = openrouter_request(api_key, model, messages, log_dir=log_dir)
    return _parse_title_evaluation_json(str(raw), n=len(candidates))


def _select_title_by_scores(
    transcript: str,
    candidates: list[str],
    scores: list[tuple[int, int]],
) -> str:
    """Pick candidate with highest combined score; tie-break with _selection_sort_key."""
    if not candidates or len(scores) != len(candidates):
        return ""

    combined = [v + c for v, c in scores]
    best = max(combined)
    tie_indices = [i for i, s in enumerate(combined) if s == best]
    best_i = min(
        tie_indices,
        key=lambda i: _selection_sort_key(transcript, candidates[i], i),
    )
    v, c = scores[best_i]
    print(
        f"Selected candidate index {best_i} (combined={best}, "
        f"verbatim={v}, correctness={c})."
    )
    return candidates[best_i]


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


def generate_title_with_openrouter(
    api_key: str,
    transcript: str,
    model: str = DEFAULT_MODEL,
    log_dir: Path | None = None,
) -> str:
    """Generate title from transcript using OpenRouter (batch candidates, batch score, select).

    Args:
        api_key: OpenRouter API key
        transcript: Transcript text
        model: OpenRouter model name for generation and scoring calls
        log_dir: If set, pass through to openrouter_transport (files under log_dir/logs/).

    Returns:
        Selected title text (single line)

    Raises:
        RuntimeError: If the transcript is empty/whitespace-only or title generation fails.
    """
    # Shared transcript for generation and scoring prompts (opening-span rules).
    title_source_transcript = transcript.strip()
    if not title_source_transcript:
        raise RuntimeError("Transcript is empty; cannot generate title.")

    # Phase 1: one generation call for the candidate pool.
    try:
        candidates = _generate_title_candidates(
            api_key,
            model,
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

    # Phase 2: one scoring call (verbatim + correctness per candidate), then argmax + tie-break.
    try:
        score_rows = _evaluate_title_candidates(
            api_key,
            model,
            title_source_transcript,
            candidates,
            log_dir,
        )
    except RuntimeError as e:
        print(f"Title batch scoring failed: {e}", file=sys.stderr)
        raise

    for i, (v, c) in enumerate(score_rows):
        print(
            f"  Candidate {i}: verbatim={v}, correctness={c}, combined={v + c}",
            file=sys.stderr,
        )

    raw_title = _select_title_by_scores(title_source_transcript, candidates, score_rows)

    if not raw_title:
        print("Title selection produced empty result.", file=sys.stderr)
        raise RuntimeError("Title generation returned empty response")

    return raw_title


def generate_title_from_transcript(
    api_key: str,
    transcript_path: Path,
    output_path: Path,
    model: str = DEFAULT_MODEL,
    log_dir: Path | None = None,
) -> None:
    """Generate title from transcript file and save to output file.

    Args:
        api_key: OpenRouter API key
        transcript_path: Path to transcript text file
        output_path: Path to save title text file
        model: OpenRouter model name for generation and scoring calls
        log_dir: If set, pass through to openrouter_transport (files under log_dir/logs/).

    Raises:
        RuntimeError: If the transcript file is empty/whitespace-only (no title file written)
            or title generation fails.
    """
    print(f"Reading transcript from: {transcript_path}")
    transcript = transcript_path.read_text(encoding="utf-8").strip()
    if not transcript:
        raise RuntimeError(
            f"Transcript file is empty or whitespace-only ({transcript_path.name}); "
            "title file not written."
        )
    # Use the full transcript for the title step; the prompt instructs the model
    # to extract from the early speech portion of the transcript.
    title_text = generate_title_with_openrouter(api_key, transcript, model=model, log_dir=log_dir)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(title_text, encoding="utf-8")
    print(f"Title saved to: {output_path}")


__all__ = [
    "DEFAULT_MODEL",
    "generate_title_with_openrouter",
    "generate_title_from_transcript",
]
