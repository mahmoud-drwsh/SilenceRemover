"""Filename sanitization utilities (pure string functions).

This package provides pure functions for converting arbitrary strings into
safe, filesystem-compatible filenames. No file I/O, no dependencies.
"""

from sr_filename.api import sanitize_filename

__all__ = ["sanitize_filename"]
