"""LLM prompt templates for title generation."""

__all__ = [
    "TITLE_PROMPT_TEMPLATE",
    "TITLE_CANDIDATES_PROMPT_TEMPLATE",
    "TITLE_CANDIDATES_SCORE_PROMPT_TEMPLATE",
]

TITLE_PROMPT_TEMPLATE = """\
Generate one YouTube video title in Arabic from the transcript below. The title must be in Arabic. Output only the title text on one line—no commentary, no explanation, no quotes around it, and nothing else.

Rules: one title only. Use YouTube title length (up to 100 characters).

1. Verbatim constraint: the title must be a verbatim contiguous span from the provided transcript (exact same Arabic words in the same order). Do not paraphrase, do not rephrase, and do not add any words.
2. Beginning-only extraction: the title is always stated at the beginning of the transcript. Extract it only from the opening complete-sentence part at the start of the transcript.
3. Do NOT use later answer/explanation body text. If a candidate phrase appears in later explanatory content, reject it and choose from the opening complete sentences instead.
4. Keep sentence integrity while selecting: choose a natural contiguous span from those opening complete sentences.
5. Length fit: if you must shorten for YouTube length limits, truncate only by removing leading/trailing words from that same opening span (keep the remaining words identical to the transcript).

Transcript:
{transcript}
"""

# Used by `src/llm/title.py` for one-shot candidate pool generation (JSON array output).
TITLE_CANDIDATES_PROMPT_TEMPLATE = """\
Generate exactly {candidate_count} distinct YouTube video titles in Arabic from the transcript below. Each title must be in Arabic.

Output format (required):
- Output only a single JSON array of exactly {candidate_count} strings, e.g. ["title1","title2","title3"].
- No markdown, no code fences, no commentary before or after the array—only valid JSON.
- Each string must be a single line (no newline characters inside a title).
- All {candidate_count} titles must be different from each other.

Rules for every title:
1. Verbatim constraint: each title must be a verbatim contiguous span from the transcript (exact same Arabic words in the same order). Do not paraphrase, rephrase, or add words.
2. Beginning-only extraction: titles come from the opening complete-sentence part at the start of the transcript (where the title is introduced).
3. Do NOT use later answer/explanation body text.
4. Keep natural contiguous spans from those opening sentences; for length, truncate only by removing leading/trailing words within the same span (words must stay identical to the transcript).
5. YouTube length: each title up to 100 characters.

Vary the chosen spans when possible (e.g. slightly different lengths) while staying verbatim and beginning-only.

Transcript:
{transcript}
"""

# Used by `src/llm/title.py` for one-shot scoring of all candidates (JSON object output).
TITLE_CANDIDATES_SCORE_PROMPT_TEMPLATE = """\
You evaluate Arabic video title candidates against a transcript. Score every candidate in order.

Transcript:
{transcript}

Candidates (JSON array, fixed order — evaluation index i corresponds to candidates[i]):
{candidates_json}

For each candidate, output two integer scores from 0 to 10 (inclusive):

1) verbatim_score (0–10): How well the string matches a single contiguous verbatim span of the transcript (same Arabic words in the same order). No paraphrase, no added words.
   - 10: exact contiguous substring match (minor whitespace/punctuation differences only).
   - 5–9: mostly verbatim but small mismatches or alignment issues.
   - 0–4: clearly not a verbatim substring or largely invented wording.

2) correctness_score (0–10): Whether it behaves like a proper title from the opening/title-intro portion (not from later answer/explanation body), with no junk prefix/suffix (e.g. "العنوان", "Title:", wrapping quotes, extra commentary).
   - 10: clearly from the opening complete-sentence title-intro region, clean single title.
   - 5–9: mostly correct position/format with minor issues.
   - 0–4: drawn from later body text, or has labels/extra commentary, or otherwise violates title-intro rules.

Output format (required):
- Output only one JSON object, no markdown fences, no commentary.
- Shape: {{"evaluations":[{{"verbatim_score":int,"correctness_score":int}}, ...]}}
- The "evaluations" array must have exactly the same length as the Candidates array above, in the same order.
- Each score must be an integer from 0 through 10.
"""
