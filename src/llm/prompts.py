"""LLM prompt templates for transcription and title generation."""

__all__ = [
    "TRANSCRIBE_PROMPT",
    "TITLE_PROMPT_TEMPLATE",
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
Generate one YouTube video title in Arabic from the transcript below. The title must be in Arabic. Output only the title—no commentary, no explanation, no quotes around it, and nothing else.

Rules: 60–90 characters (max 100). One title only.

1. Verbatim constraint: the title must be a verbatim contiguous span from the provided transcript (exact same Arabic words in the same order). Do not paraphrase, do not rephrase, and do not add any words.
2. Early selection: use only the earliest part of the transcript (first few sentences from the start of the provided transcript).
   Choose the best verbatim contiguous span within those sentences that can serve as a 60–90 character YouTube title.
3. Honorifics: do not add "سيدنا" or "ﷺ" yourself. Leave honorific insertion to the separate honorific post-processing step.
4. Length fit: if you must shorten for the 60–90 character limit, truncate by removing leading/trailing words from the span (keep the remaining words identical to the transcript).

Transcript:
{transcript}
"""

HONORIFIC_CHECK_PROMPT_TEMPLATE = """\
You are given one Arabic video title. Determine whether Islamic honorific edits are missing.

Rules to check:
1. The title should include "سيدنا" immediately before the first Prophet reference in the Prophet-related phrase/block: "محمد", "رسول الله", or "النبي المصطفى".
2. The honorific "ﷺ" must appear exactly once, immediately after the end of that Prophet-related phrase/block:
   - "محمد" -> after محمد
   - "رسول الله" (including inside "محمد رسول الله") -> after رسول الله (at the end of the block)
   - "النبي المصطفى" -> after المصطفى
   Also remove/flag any duplicate "ﷺ" that appears inside that block.
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
2. Ensure there is exactly one "ﷺ" at the end of that Prophet-related phrase/block (after محمد / after رسول الله / after المصطفى). Remove any duplicate "ﷺ" that appears earlier inside that block.

Examples (output rules):
- Input: محمد -> Output: سيدنا محمد ﷺ
- Input: محمد ﷺ -> Output: سيدنا محمد ﷺ
- Input: محمد ﷺ ﷺ -> Output: سيدنا محمد ﷺ (remove duplicate ﷺ)
- Input: محمد رسول الله -> Output: سيدنا محمد رسول الله ﷺ
- Input: محمد ﷺ رسول الله ﷺ -> Output: سيدنا محمد رسول الله ﷺ
- Input: محمد ﷺ ﷺ رسول الله ﷺ ﷺ -> Output: سيدنا محمد رسول الله ﷺ (remove extra duplicates)
- Input: النبي المصطفى -> Output: سيدنا النبي المصطفى ﷺ
- Input: رسول الله -> Output: سيدنا رسول الله ﷺ

If the title already follows these rules and needs no changes, return the title exactly as-is.

Output only the final title text on one line. No commentary, no explanation, no extra formatting.

Title:
{title}
"""

ADD_HONORIFIC_PROMPT_TEMPLATE = HONORIFIC_APPLY_PROMPT_TEMPLATE
