"""Path escaping utilities for FFmpeg filter graphs.

Pure string processing functions for safely embedding paths in FFmpeg filter arguments.
"""


def _escape_ffmpeg_single_quoted_path(value: str) -> str:
    """Escape a value for inclusion in a single-quoted FFmpeg filter argument.
    
    We currently only expect filesystem paths here; the main risk is a literal `'`
    character breaking the filter syntax.
    
    FFmpeg's filter parser is not the same as Python's or shell quoting, but
    escaping single quotes is still the practical minimum for safety.
    
    Args:
        value: The string to escape (typically a file path)
        
    Returns:
        Escaped string safe for FFmpeg single-quoted arguments
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")
