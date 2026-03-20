"""LLM prompt templates for transcription and title generation."""

__all__ = [
    "TRANSCRIBE_PROMPT",
    "TITLE_PROMPT_TEMPLATE",
    "TITLE_VERBATIM_CHECK_PROMPT_TEMPLATE",
    "HONORIFIC_CHECK_PROMPT_TEMPLATE",
    "HONORIFIC_APPLY_PROMPT_TEMPLATE",
    "ADD_HONORIFIC_PROMPT_TEMPLATE",
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

Output exactly one token: YES or NO (no punctuation, no extra text).
CandidateTitle:
{candidate_title}
"""

HONORIFIC_CHECK_PROMPT_TEMPLATE = """\
You are given one Arabic video title. Determine whether Islamic honorific edits are missing.

Rules to check:
1. The title should include "سيدنا" immediately before the first Prophet reference in the Prophet-related phrase/block: "محمد", "رسول الله", or "النبي المصطفى".
2. The honorific "ﷺ":
   - Normally, it must appear exactly once immediately after the end of that Prophet-related phrase/block:
     - "محمد" -> after محمد
     - "رسول الله" (including inside "محمد رسول الله") -> after رسول الله (at the end of the block)
     - "النبي المصطفى" -> after المصطفى
   - Exception: if the title contains "عليه الصلاة والسلام" or "عليه السلام" immediately after the Prophet reference within that phrase/block, then do NOT require/expect any extra "ﷺ" for that Prophet mention.
     - If "ﷺ" appears immediately after "عليه الصلاة والسلام" / "عليه السلام", that "ﷺ" is unnecessary and should be removed (so return YES).
Also remove/flag any duplicate "ﷺ" that appears inside that block (unless the exception rule above applies).
3. Return YES if "سيدنا" and/or "ﷺ" placement is missing or duplicated; otherwise return NO.

Examples (where "ﷺ" should be added vs not added):
- Title: محمد -> honorific edits missing (missing سيدنا and ﷺ), return YES
- Title: سيدنا محمد ﷺ -> follows rules, return NO
- Title: محمد ﷺ -> honorific edits missing (missing سيدنا), return YES
- Title: محمد ﷺ ﷺ -> honorific edits missing (duplicate ﷺ), return YES
- Title: محمد رسول الله -> honorific edits missing (missing سيدنا prefix and ending ﷺ), return YES
- Title: سيدنا محمد رسول الله ﷺ -> follows rules, return NO
- Title: محمد ﷺ رسول الله ﷺ -> honorific edits missing (ﷺ duplicated inside block), return YES
- Title: النبي المصطفى -> honorific edits missing (missing سيدنا prefix and ending ﷺ), return YES
- Title: سيدنا النبي المصطفى ﷺ -> follows rules, return NO
- Title: رسول الله -> honorific edits missing (missing سيدنا prefix and ending ﷺ), return YES
- Title: سيدنا رسول الله ﷺ -> follows rules, return NO
- Title: آل سيدنا النبي عليه الصلاة والسلام -> follows rules (no extra ﷺ needed), return NO
- Title: آل سيدنا النبي عليه الصلاة والسلام ﷺ -> unnecessary extra ﷺ after "عليه الصلاة والسلام", return YES
- Title: آل النبي عليه الصلاة والسلام -> honorific edits missing (missing سيدنا), return YES
- Title: سيدنا النبي عليه الصلاة والسلام -> follows rules (no extra ﷺ needed), return NO
- Title: سيدنا النبي عليه الصلاة والسلام ﷺ -> unnecessary extra ﷺ after "عليه الصلاة والسلام", return YES

If the title already follows the rules, return:
NO
If any title change is needed, return:
YES

Output exactly one token and nothing else. No commentary, no explanation, and no markdown.

Title:
{title}
"""

HONORIFIC_APPLY_PROMPT_TEMPLATE = """\
You are given an Arabic video title. Your task is to add Islamic honorifics where they are missing—do not duplicate any that are already present.

1. Ensure "سيدنا" appears immediately before the Prophet-related phrase/block that starts with any of: "محمد", "رسول الله", or "النبي المصطفى". If "سيدنا" is already there, leave it.
2. Ensure the salawat honorific "ﷺ" placement follows these rules:
   - Normally, ensure there is exactly one "ﷺ" at the end of that Prophet-related phrase/block (after محمد / after رسول الله / after المصطفى). Remove any duplicate "ﷺ" that appears earlier inside that block.
   - Exception: if the Prophet-related phrase/block contains "عليه الصلاة والسلام" or "عليه السلام", then do NOT add any extra "ﷺ" after that phrase. If there is an extra "ﷺ" immediately after "عليه الصلاة والسلام"/"عليه السلام", remove it.

Examples (output rules):
- Input: محمد -> Output: سيدنا محمد ﷺ
- Input: محمد ﷺ -> Output: سيدنا محمد ﷺ
- Input: محمد ﷺ ﷺ -> Output: سيدنا محمد ﷺ (remove duplicate ﷺ)
- Input: محمد رسول الله -> Output: سيدنا محمد رسول الله ﷺ
- Input: محمد ﷺ رسول الله ﷺ -> Output: سيدنا محمد رسول الله ﷺ
- Input: محمد ﷺ ﷺ رسول الله ﷺ ﷺ -> Output: سيدنا محمد رسول الله ﷺ (remove extra duplicates)
- Input: النبي المصطفى -> Output: سيدنا النبي المصطفى ﷺ
- Input: رسول الله -> Output: سيدنا رسول الله ﷺ
- Input: آل سيدنا النبي عليه الصلاة والسلام -> Output: آل سيدنا النبي عليه الصلاة والسلام
- Input: آل سيدنا النبي عليه الصلاة والسلام ﷺ -> Output: آل سيدنا النبي عليه الصلاة والسلام
- Input: آل النبي عليه الصلاة والسلام -> Output: آل سيدنا النبي عليه الصلاة والسلام
- Input: سيدنا النبي عليه الصلاة والسلام -> Output: سيدنا النبي عليه الصلاة والسلام
- Input: سيدنا النبي عليه الصلاة والسلام ﷺ -> Output: سيدنا النبي عليه الصلاة والسلام
- Input: النبي عليه الصلاة والسلام -> Output: سيدنا النبي عليه الصلاة والسلام

If the title already follows these rules and needs no changes, return the title exactly as-is.

Output only the final title text on one line. No commentary, no explanation, no extra formatting.

Title:
{title}
"""

ADD_HONORIFIC_PROMPT_TEMPLATE = HONORIFIC_APPLY_PROMPT_TEMPLATE
