"""Prompt template for audio transcription."""

TRANSCRIBE_PROMPT = """Transcribe the Arabic audio as clean verbatim Arabic text.

Rules:
- Output only the transcript text.
- No timestamps.
- No speaker labels.
- Do not summarize, paraphrase, correct, or explain.
- Preserve the original wording as much as possible.
- Preserve the opening sentences especially carefully.
- Keep punctuation where it is helpful and natural.
- If a word is unclear, choose the most likely wording, but do not invent content.
- Do not repeat phrases unless they are actually repeated in the audio.
- Stop when the audio content ends; do not continue with guessed or filler text."""

__all__ = ["TRANSCRIBE_PROMPT"]
