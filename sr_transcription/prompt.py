"""Prompt template for audio transcription."""

TRANSCRIBE_PROMPT = """Transcribe the Arabic audio as clean verbatim text in Arabic.
- No timestamps
- No speaker labels
- Preserve the original wording as much as possible (do not paraphrase, summarize, or correct phrasing).
- Keep punctuation as in the audio where possible.
- If a word is unclear, choose the most likely wording, but do not invent new content."""

__all__ = ["TRANSCRIBE_PROMPT"]