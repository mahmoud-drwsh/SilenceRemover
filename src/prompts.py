"""LLM prompt templates for transcription and title generation."""

__all__ = [
    "TRANSCRIBE_PROMPT",
    "TITLE_PROMPT_TEMPLATE",
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

ADD_HONORIFIC_PROMPT_TEMPLATE = """\
You are given an Arabic video title. Your task is to add Islamic honorifics where they are missing—do not duplicate if already present.

1. Before the name محمد only (not before رسول الله، المصطى، النبي), add سيدنا immediately before محمد. If سيدنا is already there, leave it.
2. Immediately after each mention of the Prophet in the title (e.g. محمد، رسول الله، المصطى، النبي), add the honorific ﷺ. If ﷺ is already after that mention, do not add it again.

If the given title already follows these rules and needs no changes, return it exactly as-is.

Output only the final title, nothing else. No commentary.

Title:
{title}
"""
