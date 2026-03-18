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
- Keep punctuation and natural phrasing."""

TITLE_PROMPT_TEMPLATE = """\
Generate one YouTube video title in Arabic from the transcript below. The title must be in Arabic. Output only the title—no commentary, no explanation, no quotes around it, and nothing else.

Rules: 60–90 characters (max 100). One title only. Be accurate and descriptive; prefer wording from the transcript.

Transcript:
{transcript}
"""

HONORIFIC_CHECK_PROMPT_TEMPLATE = """\
You are given one Arabic video title. Determine whether Islamic honorific edits are missing.

Rules to check:
1. Before the name "محمد" only (not before رسول الله, المصطفى, or النبي), "سيدنا" should appear immediately before محمد.
2. Immediately after each mention of the Prophet (محمد, رسول الله, المصطفى, النبي), the honorific "ﷺ" should appear.
3. A single title must only be modified when one or more of the above is missing.

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

1. Before the name محمد only (not before رسول الله, المصطفى, النبي), add سيدنا immediately before محمد. If سيدنا is already there, leave it.
2. Immediately after each mention of the Prophet in the title (محمد, رسول الله, المصطفى, النبي), add the honorific ﷺ. If ﷺ is already after that mention, do not add it again.

If the title already follows these rules and needs no changes, return the title exactly as-is.

Output only the final title text on one line. No commentary, no explanation, no extra formatting.

Title:
{title}
"""

ADD_HONORIFIC_PROMPT_TEMPLATE = HONORIFIC_APPLY_PROMPT_TEMPLATE
