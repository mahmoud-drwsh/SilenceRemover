"""Unit tests for sr_filename package.

Tests for filename sanitization - pure string functions with no file I/O.
"""

import sys
from pathlib import Path

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

import pytest

from sr_filename import sanitize_filename


class TestBasicSanitization:
    """Test basic filename sanitization."""
    
    def test_simple_string_unchanged(self):
        """Test that simple strings pass through unchanged."""
        assert sanitize_filename("My Video Title") == "My Video Title"
    
    def test_lowercase_unchanged(self):
        """Test that lowercase strings work."""
        assert sanitize_filename("title") == "title"
    
    def test_numbers_and_letters(self):
        """Test alphanumeric combinations."""
        assert sanitize_filename("Video123") == "Video123"
    
    def test_underscores_preserved(self):
        """Test that underscores are preserved."""
        assert sanitize_filename("my_video_title") == "my_video_title"
    
    def test_dashes_preserved(self):
        """Test that dashes are preserved."""
        assert sanitize_filename("my-video-title") == "my-video-title"


class TestQuoteStripping:
    """Test quote stripping functionality."""
    
    def test_leading_double_quotes_stripped(self):
        """Test that leading double quotes are stripped."""
        assert sanitize_filename('"Title') == "Title"
    
    def test_trailing_double_quotes_stripped(self):
        """Test that trailing double quotes are stripped."""
        assert sanitize_filename('Title"') == "Title"
    
    def test_both_double_quotes_stripped(self):
        """Test that both leading and trailing double quotes are stripped."""
        assert sanitize_filename('"Title"') == "Title"
    
    def test_leading_single_quotes_stripped(self):
        """Test that leading single quotes are stripped."""
        assert sanitize_filename("'Title") == "Title"
    
    def test_trailing_single_quotes_stripped(self):
        """Test that trailing single quotes are stripped."""
        assert sanitize_filename("Title'") == "Title"
    
    def test_both_single_quotes_stripped(self):
        """Test that both leading and trailing single quotes are stripped."""
        assert sanitize_filename("'Title'") == "Title"
    
    def test_inner_quotes_preserved(self):
        """Test that inner quotes are replaced with spaces."""
        assert sanitize_filename('Title "Subtitle"') == "Title Subtitle"


class TestReservedCharacters:
    """Test replacement of reserved filesystem characters."""
    
    def test_forward_slash_replaced(self):
        """Test that forward slashes become spaces."""
        assert sanitize_filename("Title/Subtitle") == "Title Subtitle"
    
    def test_backslash_replaced(self):
        """Test that backslashes become spaces."""
        assert sanitize_filename("Title\\Subtitle") == "Title Subtitle"
    
    def test_colon_replaced(self):
        """Test that colons become spaces."""
        assert sanitize_filename("Title: Subtitle") == "Title Subtitle"
    
    def test_asterisk_replaced(self):
        """Test that asterisks become spaces."""
        assert sanitize_filename("Title*Subtitle") == "Title Subtitle"
    
    def test_question_mark_replaced(self):
        """Test that question marks become spaces."""
        assert sanitize_filename("Title?Subtitle") == "Title Subtitle"
    
    def test_less_than_replaced(self):
        """Test that less-than signs become spaces."""
        assert sanitize_filename("Title<Subtitle") == "Title Subtitle"
    
    def test_greater_than_replaced(self):
        """Test that greater-than signs become spaces."""
        assert sanitize_filename("Title>Subtitle") == "Title Subtitle"
    
    def test_pipe_replaced(self):
        """Test that pipe characters become spaces."""
        assert sanitize_filename("Title|Subtitle") == "Title Subtitle"
    
    def test_multiple_reserved_chars(self):
        """Test multiple reserved characters all replaced."""
        assert sanitize_filename("Title/\\:*?\"<>|Subtitle") == "Title Subtitle"


class TestWhitespaceHandling:
    """Test whitespace collapse and handling."""
    
    def test_multiple_spaces_collapsed(self):
        """Test that multiple spaces are collapsed to single space."""
        assert sanitize_filename("Title    Subtitle") == "Title Subtitle"
    
    def test_leading_spaces_stripped(self):
        """Test that leading spaces are stripped."""
        assert sanitize_filename("  Title") == "Title"
    
    def test_trailing_spaces_stripped(self):
        """Test that trailing spaces are stripped."""
        assert sanitize_filename("Title  ") == "Title"
    
    def test_leading_trailing_spaces_stripped(self):
        """Test that both leading and trailing spaces are stripped."""
        assert sanitize_filename("  Title  ") == "Title"
    
    def test_mixed_whitespace_collapsed(self):
        """Test that mixed whitespace (spaces, tabs) is handled."""
        # Tabs are removed in step 1, so "Title\tSubtitle" becomes "TitleSubtitle"
        # Then no spaces to collapse
        assert sanitize_filename("Title\tSubtitle") == "TitleSubtitle"


class TestControlCharacters:
    """Test removal of dangerous control characters."""
    
    def test_null_bytes_removed(self):
        """Test that null bytes are removed."""
        assert sanitize_filename("Title\x00Subtitle") == "TitleSubtitle"
    
    def test_newlines_removed(self):
        """Test that newlines are removed."""
        assert sanitize_filename("Title\nSubtitle") == "TitleSubtitle"
    
    def test_carriage_return_removed(self):
        """Test that carriage returns are removed."""
        assert sanitize_filename("Title\rSubtitle") == "TitleSubtitle"
    
    def test_tabs_removed(self):
        """Test that tabs are removed."""
        assert sanitize_filename("Title\tSubtitle") == "TitleSubtitle"
    
    def test_all_control_chars_removed(self):
        """Test that all control chars are removed."""
        assert sanitize_filename("\0\n\r\tTitle\0\n\r\t") == "Title"


class TestEmptyAndFallback:
    """Test empty string handling and fallback."""
    
    def test_empty_string_returns_untitled(self):
        """Test that empty string returns 'untitled'."""
        assert sanitize_filename("") == "untitled"
    
    def test_whitespace_only_returns_untitled(self):
        """Test that whitespace-only returns 'untitled'."""
        assert sanitize_filename("   ") == "untitled"
    
    def test_tabs_only_returns_untitled(self):
        """Test that tabs-only returns 'untitled'."""
        assert sanitize_filename("\t\t\t") == "untitled"
    
    def test_newlines_only_returns_untitled(self):
        """Test that newlines-only returns 'untitled'."""
        assert sanitize_filename("\n\n\n") == "untitled"
    
    def test_reserved_chars_only_returns_untitled(self):
        """Test that reserved chars only returns 'untitled'."""
        assert sanitize_filename("///") == "untitled"
    
    def test_mixed_whitespace_reserved_returns_untitled(self):
        """Test mixed whitespace and reserved returns 'untitled'."""
        assert sanitize_filename("  \t///\n  ") == "untitled"


class TestLengthTruncation:
    """Test 200-character length limit."""
    
    def test_short_string_not_truncated(self):
        """Test that short strings are not truncated."""
        assert sanitize_filename("Short") == "Short"
    
    def test_exactly_200_chars_not_truncated(self):
        """Test that exactly 200 chars is preserved."""
        long_title = "x" * 200
        assert len(sanitize_filename(long_title)) == 200
    
    def test_over_200_chars_truncated(self):
        """Test that over 200 chars is truncated."""
        long_title = "x" * 250
        result = sanitize_filename(long_title)
        assert len(result) == 200
        assert result == "x" * 200
    
    def test_truncation_with_spaces(self):
        """Test truncation with spaces at the end."""
        # 200 chars with space at position 200
        long_title = "x" * 199 + " " + "y" * 50
        result = sanitize_filename(long_title)
        # Should be truncated to 200, trailing space removed by strip
        assert len(result) <= 200


class TestUnicodeAndSpecialChars:
    """Test Unicode and special character handling."""
    
    def test_arabic_text_preserved(self):
        """Test that Arabic text is preserved."""
        assert sanitize_filename("مرحبا بالعالم") == "مرحبا بالعالم"
    
    def test_chinese_text_preserved(self):
        """Test that Chinese text is preserved."""
        assert sanitize_filename("你好世界") == "你好世界"
    
    def test_emoji_preserved(self):
        """Test that emoji are preserved."""
        assert sanitize_filename("Title 🎬") == "Title 🎬"
    
    def test_mixed_unicode_and_ascii(self):
        """Test mixed Unicode and ASCII."""
        assert sanitize_filename("Hello مرحبا 你好") == "Hello مرحبا 你好"


class TestRealWorldExamples:
    """Test real-world video title examples."""
    
    def test_title_with_quotes(self):
        """Test title with quotes."""
        assert sanitize_filename('The "Best" Video') == "The Best Video"
    
    def test_title_with_colon(self):
        """Test title with colon."""
        assert sanitize_filename("Tutorial: How to Code") == "Tutorial How to Code"
    
    def test_title_with_question(self):
        """Test title with question mark."""
        assert sanitize_filename("What is Python?") == "What is Python"
    
    def test_title_with_date(self):
        """Test title with date-like format."""
        assert sanitize_filename("Video 2024-03-15") == "Video 2024-03-15"
    
    def test_title_with_version(self):
        """Test title with version number."""
        assert sanitize_filename("App v1.2.3") == "App v1.2.3"
    
    def test_complex_arabic_title(self):
        """Test complex Arabic title with punctuation."""
        title = 'شرح: "كيفية البرمجة"'
        result = sanitize_filename(title)
        assert "شرح" in result
        assert "كيفية البرمجة" in result
        assert '"' not in result
        assert ':' not in result


class TestEdgeCases:
    """Test edge cases and corner cases."""
    
    def test_single_character(self):
        """Test single character input."""
        assert sanitize_filename("x") == "x"
    
    def test_single_quote(self):
        """Test single quote input."""
        assert sanitize_filename("'") == "untitled"
    
    def test_single_double_quote(self):
        """Test single double quote input."""
        assert sanitize_filename('"') == "untitled"
    
    def test_only_spaces(self):
        """Test only spaces input."""
        assert sanitize_filename("     ") == "untitled"
    
    def test_very_long_with_special_chars(self):
        """Test very long input with special chars scattered throughout."""
        title = "Video" + "/" * 50 + "Title" + "?" * 50 + "End"
        result = sanitize_filename(title)
        assert "Video" in result
        assert "Title" in result
        assert "End" in result
        assert "/" not in result
        assert "?" not in result
        assert len(result) <= 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
