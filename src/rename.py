"""Filename sanitization for title-based output basenames (used when resolving final video filenames)."""


def _sanitize_filename(name: str) -> str:
    cleaned = "".join(c for c in name if c not in "\0\n\r\t").strip().strip('"').strip("'")
    for ch in ["/", "\\", ":", "*", "?", "\"", "<", ">", "|"]:
        cleaned = cleaned.replace(ch, " ")
    return (" ".join(cleaned.split()) or "untitled")[:200]


def sanitize_filename(name: str) -> str:
    """Public alias for _sanitize_filename. Use when resolving output basename from title."""
    return _sanitize_filename(name)
