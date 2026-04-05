"""FFmpeg progress line parsing utilities.

Pure functions for parsing FFmpeg -progress output lines.
"""


def parse_progress_seconds(line: str) -> float | None:
    """Parse FFmpeg -progress output line into seconds.
    
    Handles two formats:
    - out_time_ms=1234567 (microseconds since start)
    - out_time=01:23:45.678 (HH:MM:SS.mmm timecode)
    
    Args:
        line: A single line from FFmpeg -progress output
        
    Returns:
        Seconds as float, or None if line doesn't match expected formats
        
    Examples:
        >>> parse_progress_seconds("out_time_ms=1234567")
        1.234567
        >>> parse_progress_seconds("out_time=00:01:30.500")
        90.5
        >>> parse_progress_seconds("frame=123")
        None
    """
    if line.startswith("out_time_ms="):
        try:
            return float(line.split("=", 1)[1]) / 1_000_000.0
        except (ValueError, IndexError):
            return None
    if line.startswith("out_time="):
        value = line.split("=", 1)[1]
        try:
            hours, minutes, seconds = value.split(":")
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except (ValueError, TypeError, IndexError):
            return None
    return None
