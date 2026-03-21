"""LLM prompt templates for transcription and title generation."""

__all__ = [
    "TRANSCRIBE_PROMPT",
    "TITLE_PROMPT_TEMPLATE",
    "TITLE_CANDIDATES_PROMPT_TEMPLATE",
    "TITLE_VERBATIM_CHECK_PROMPT_TEMPLATE",
]

TRANSCRIBE_PROMPT = """Transcribe the Arabic audio as clean verbatim text in Arabic.
- No timestamps
- No speaker labels
- Preserve the original wording as much as possible (do not paraphrase, summarize, or correct phrasing).
- Keep punctuation as in the audio where possible.
- If a word is unclear, choose the most likely wording, but do not invent new content."""

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

TITLE_VERBATIM_CHECK_PROMPT_TEMPLATE = """\
You are given:
- Transcript: {transcript}
- CandidateTitle: {candidate_title}

Task:
Verify whether CandidateTitle is a verbatim title taken from the Transcript with no extra words or commentary.

Rules:
1. The candidate must not include any prefix/suffix like "العنوان", "Title:", quotes, or any extra commentary.
2. The candidate must not introduce any words that do not appear in the transcript.
3. Source-position constraint: the candidate must come from the opening complete-sentence part at the start of the transcript (where the title is introduced), not from later answer/explanatory content.
4. Minor differences in whitespace/punctuation are allowed.

Output exactly one token: YES or NO. Optional single trailing punctuation (e.g. `YES.`) is allowed; no other text.
CandidateTitle:
{candidate_title}
"""
