"""Filename sanitization utilities.

Pure string functions for converting titles and names into safe filesystem-compatible
filenames. No file I/O, no dependencies.
"""

import sys

# Platform detection (currently used for max filename length only)
# Cross-platform: use Windows-compatible 200 char limit everywhere for consistency
RESERVED_CHARS = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
MAX_FILENAME_LENGTH = 200


def sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filesystem filename.
    
    Performs the following transformations:
    1. Removes null bytes, newlines, carriage returns, and tabs
    2. Strips leading/trailing quotes (" and ')
    3. Replaces reserved filesystem characters with spaces
    4. Collapses multiple spaces into single spaces
    5. Falls back to "untitled" if result is empty
    6. Truncates to platform-specific max length (Windows: 200, Unix: 255)
    
    Reserved characters replaced on ALL platforms (cross-platform safety):
    / \\ : * ? " < > |
    
    Args:
        name: The input string to sanitize (typically a video title)
        
    Returns:
        A safe filename string suitable for use as a basename
        
    Examples:
        >>> sanitize_filename("My Video Title")
        'My Video Title'
        >>> sanitize_filename('Title With "Quotes"')
        'Title With Quotes'
        >>> sanitize_filename("Title/With\\Slashes")
        'Title With Slashes'
        >>> sanitize_filename("")
        'untitled'
        >>> sanitize_filename("   ")
        'untitled'
    """
    # Step 1: Remove dangerous control characters
    cleaned = "".join(c for c in name if c not in "\0\n\r\t").strip()
    
    # Step 2: Strip leading/trailing quotes
    cleaned = cleaned.strip('"').strip("'")
    
    # Step 3: Replace reserved filesystem chars with spaces
    for ch in RESERVED_CHARS:
        cleaned = cleaned.replace(ch, " ")
    
    # Step 4: Collapse multiple spaces and handle empty result
    cleaned = " ".join(cleaned.split())
    
    # Step 5: Fallback to "untitled" if empty
    if not cleaned:
        cleaned = "untitled"
    
    # Step 6: Truncate to platform-specific max length
    return cleaned[:MAX_FILENAME_LENGTH]
