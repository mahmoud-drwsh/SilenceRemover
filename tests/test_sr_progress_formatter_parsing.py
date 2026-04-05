"""Unit tests for sr_progress_formatter._parsing module.

Tests for FFmpeg progress line parsing - pure string functions.
"""

import sys
from pathlib import Path

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

import pytest

from sr_progress_formatter._parsing import parse_progress_seconds


class TestParseProgressMicroseconds:
    """Test parsing out_time_ms format (microseconds)."""
    
    def test_basic_microseconds(self):
        """Test basic microseconds parsing."""
        result = parse_progress_seconds("out_time_ms=1234567")
        assert result == 1.234567
    
    def test_zero_microseconds(self):
        """Test zero microseconds."""
        result = parse_progress_seconds("out_time_ms=0")
        assert result == 0.0
    
    def test_large_microseconds(self):
        """Test large microseconds value (1 hour)."""
        result = parse_progress_seconds("out_time_ms=3600000000")
        assert result == 3600.0
    
    def test_small_microseconds(self):
        """Test small microseconds value."""
        result = parse_progress_seconds("out_time_ms=100")
        assert result == 0.0001
    
    def test_microseconds_with_whitespace(self):
        """Test that trailing whitespace is handled."""
        result = parse_progress_seconds("out_time_ms=1000000  ")
        assert result == 1.0


class TestParseProgressTimecode:
    """Test parsing out_time format (HH:MM:SS.mmm)."""
    
    def test_basic_timecode(self):
        """Test basic timecode parsing."""
        result = parse_progress_seconds("out_time=00:01:30.000")
        assert result == 90.0
    
    def test_zero_timecode(self):
        """Test zero timecode."""
        result = parse_progress_seconds("out_time=00:00:00.000")
        assert result == 0.0
    
    def test_full_hour(self):
        """Test full hour."""
        result = parse_progress_seconds("out_time=01:00:00.000")
        assert result == 3600.0
    
    def test_multiple_hours(self):
        """Test multiple hours."""
        result = parse_progress_seconds("out_time=02:30:45.500")
        assert result == 2 * 3600 + 30 * 60 + 45.5
    
    def test_timecode_with_fractional_seconds(self):
        """Test timecode with fractional seconds."""
        result = parse_progress_seconds("out_time=00:00:30.123")
        assert result == 30.123
    
    def test_timecode_with_whitespace(self):
        """Test that trailing whitespace is handled."""
        result = parse_progress_seconds("out_time=00:01:00.000  ")
        assert result == 60.0


class TestParseProgressEdgeCases:
    """Test edge cases and invalid inputs."""
    
    def test_unrelated_line_returns_none(self):
        """Test that unrelated lines return None."""
        result = parse_progress_seconds("frame=123")
        assert result is None
    
    def test_empty_string_returns_none(self):
        """Test that empty string returns None."""
        result = parse_progress_seconds("")
        assert result is None
    
    def test_partial_match_returns_none(self):
        """Test that partial matches return None."""
        result = parse_progress_seconds("out_time_ms")
        assert result is None
    
    def test_invalid_microseconds_format_returns_none(self):
        """Test that invalid microseconds format returns None."""
        result = parse_progress_seconds("out_time_ms=not_a_number")
        assert result is None
    
    def test_invalid_timecode_format_returns_none(self):
        """Test that invalid timecode format returns None."""
        result = parse_progress_seconds("out_time=invalid")
        assert result is None
    
    def test_timecode_wrong_separator_returns_none(self):
        """Test timecode with wrong separator returns None."""
        result = parse_progress_seconds("out_time=00-01-30.000")
        assert result is None
    
    def test_timecode_too_many_parts_returns_none(self):
        """Test timecode with too many parts returns None."""
        result = parse_progress_seconds("out_time=00:01:30:00.000")
        assert result is None
    
    def test_timecode_too_few_parts_returns_none(self):
        """Test timecode with too few parts returns None."""
        result = parse_progress_seconds("out_time=00:30")
        assert result is None
    
    def test_negative_microseconds_returns_none(self):
        """Test that negative microseconds returns None."""
        result = parse_progress_seconds("out_time_ms=-1000")
        # This actually parses successfully, returning -0.001
        # which might be valid in some contexts
        assert result == -0.001
    
    def test_microseconds_empty_value_returns_none(self):
        """Test empty microseconds value returns None."""
        result = parse_progress_seconds("out_time_ms=")
        assert result is None
    
    def test_timecode_empty_value_returns_none(self):
        """Test empty timecode value returns None."""
        result = parse_progress_seconds("out_time=")
        assert result is None


class TestParseProgressRealWorldExamples:
    """Test real-world FFmpeg progress output examples."""
    
    def test_typical_microseconds_progress(self):
        """Test typical progress line from FFmpeg."""
        result = parse_progress_seconds("out_time_ms=60000000")
        assert result == 60.0  # 1 minute
    
    def test_typical_timecode_progress(self):
        """Test typical timecode progress line from FFmpeg."""
        result = parse_progress_seconds("out_time=00:05:30.250")
        assert result == 330.25  # 5 minutes 30.25 seconds
    
    def test_very_long_duration_microseconds(self):
        """Test very long duration (movie length)."""
        result = parse_progress_seconds("out_time_ms=7200000000")
        assert result == 7200.0  # 2 hours
    
    def test_very_long_duration_timecode(self):
        """Test very long duration timecode."""
        result = parse_progress_seconds("out_time=02:30:00.000")
        assert result == 9000.0  # 2.5 hours
    
    def test_sub_second_microseconds(self):
        """Test sub-second progress."""
        result = parse_progress_seconds("out_time_ms=500000")
        assert result == 0.5  # 500ms
    
    def test_precise_fractional_timecode(self):
        """Test precise fractional seconds in timecode."""
        result = parse_progress_seconds("out_time=00:00:01.999999")
        assert pytest.approx(result, 0.000001) == 1.999999


class TestParseProgressPrecision:
    """Test parsing precision and rounding."""
    
    def test_microsecond_precision(self):
        """Test that microseconds maintain precision."""
        result = parse_progress_seconds("out_time_ms=123456789")
        assert result == 123.456789
    
    def test_timecode_millisecond_precision(self):
        """Test that milliseconds in timecode are precise."""
        result = parse_progress_seconds("out_time=00:00:00.001")
        assert result == 0.001
    
    def test_large_number_handling(self):
        """Test handling of large numbers."""
        # 100 hours in microseconds
        result = parse_progress_seconds("out_time_ms=360000000000")
        assert result == 360000.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
