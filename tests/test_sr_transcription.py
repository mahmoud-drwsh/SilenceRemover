"""Unit tests for sr_transcription package.

Tests cover audio transcription workflow with mocked OpenRouter API calls.
Uses real temp directories for file I/O testing.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

import pytest

from sr_transcription import (
    DEFAULT_MODEL,
    TRANSCRIBE_PROMPT,
    transcribe_and_save,
    transcribe_with_openrouter,
)


class TestTranscribeWithOpenRouter:
    """Test transcribe_with_openrouter function."""
    
    def test_successful_transcription(self, tmp_path):
        """Test successful transcription returns text."""
        # Create a dummy audio file
        audio_path = tmp_path / "test.ogg"
        audio_path.write_bytes(b"fake audio data")
        
        with patch("sr_transcription.api._openrouter_request") as mock_request:
            mock_request.return_value = "This is the transcript."
            
            result = transcribe_with_openrouter(
                api_key="test-key",
                audio_path=audio_path,
            )
            
            assert result == "This is the transcript."
            mock_request.assert_called_once()
    
    def test_empty_response(self, tmp_path):
        """Test that empty string response is returned as-is."""
        audio_path = tmp_path / "test.ogg"
        audio_path.write_bytes(b"fake audio data")
        
        with patch("sr_transcription.api._openrouter_request") as mock_request:
            mock_request.return_value = ""
            
            result = transcribe_with_openrouter(
                api_key="test-key",
                audio_path=audio_path,
            )
            
            assert result == ""
    
    def test_whitespace_response_passed_through(self, tmp_path):
        """Test that whitespace-only response is passed through (transcribe_and_save validates it)."""
        audio_path = tmp_path / "test.ogg"
        audio_path.write_bytes(b"fake audio data")
        
        with patch("sr_transcription.api._openrouter_request") as mock_request:
            mock_request.return_value = "   \n  "
            
            result = transcribe_with_openrouter(
                api_key="test-key",
                audio_path=audio_path,
            )
            
            # Transcription layer passes through as-is (validation happens in transcribe_and_save)
            assert result == "   \n  "
    
    def test_multiline_transcript(self, tmp_path):
        """Test multi-line transcript handling."""
        audio_path = tmp_path / "test.ogg"
        audio_path.write_bytes(b"fake audio data")
        
        with patch("sr_transcription.api._openrouter_request") as mock_request:
            mock_request.return_value = "Line 1\nLine 2\nLine 3"
            
            result = transcribe_with_openrouter(
                api_key="test-key",
                audio_path=audio_path,
            )
            
            assert result == "Line 1\nLine 2\nLine 3"
    
    def test_unicode_arabic_text(self, tmp_path):
        """Test Arabic text transcription."""
        audio_path = tmp_path / "test.ogg"
        audio_path.write_bytes(b"fake audio data")
        
        with patch("sr_transcription.api._openrouter_request") as mock_request:
            mock_request.return_value = "مرحبا بالعالم"
            
            result = transcribe_with_openrouter(
                api_key="test-key",
                audio_path=audio_path,
            )
            
            assert result == "مرحبا بالعالم"
    
    def test_api_error_propagation(self, tmp_path):
        """Test that API errors propagate correctly."""
        audio_path = tmp_path / "test.ogg"
        audio_path.write_bytes(b"fake audio data")
        
        with patch("sr_transcription.api._openrouter_request") as mock_request:
            mock_request.side_effect = RuntimeError("API failed")
            
            with pytest.raises(RuntimeError, match="API failed"):
                transcribe_with_openrouter(
                    api_key="test-key",
                    audio_path=audio_path,
                )

    def test_empty_audio_file_raises_before_provider_request(self, tmp_path):
        """Test that zero-byte audio fails fast without hitting the provider."""
        audio_path = tmp_path / "empty.ogg"
        audio_path.write_bytes(b"")

        with patch("sr_transcription.api._openrouter_request") as mock_request:
            with pytest.raises(RuntimeError, match="empty"):
                transcribe_with_openrouter(
                    api_key="test-key",
                    audio_path=audio_path,
                )

            mock_request.assert_not_called()
    
    def test_correct_api_arguments(self, tmp_path):
        """Test that correct arguments are passed to transport layer."""
        audio_path = tmp_path / "test.ogg"
        audio_path.write_bytes(b"fake audio data")
        
        with patch("sr_transcription.api._openrouter_request") as mock_request:
            mock_request.return_value = "transcript"
            
            transcribe_with_openrouter(
                api_key="test-key",
                audio_path=audio_path,
                model="test-model",
                log_dir=tmp_path / "logs",
            )
            
            # Verify call arguments
            call_args = mock_request.call_args
            assert call_args[0][0] == "test-key"  # api_key
            assert call_args[0][1] == "test-model"  # model
            assert call_args[1]["log_dir"] == tmp_path / "logs"
    
    def test_message_structure(self, tmp_path):
        """Test that messages have correct OpenAI-style structure."""
        audio_path = tmp_path / "test.ogg"
        audio_path.write_bytes(b"fake audio data")
        
        with patch("sr_transcription.api._openrouter_request") as mock_request:
            mock_request.return_value = "transcript"
            
            transcribe_with_openrouter(
                api_key="test-key",
                audio_path=audio_path,
            )
            
            # Extract messages from call
            call_args = mock_request.call_args
            messages = call_args[0][2]  # Third positional argument
            
            # Verify message structure
            assert len(messages) == 1
            assert messages[0]["role"] == "user"
            assert len(messages[0]["content"]) == 2
            assert messages[0]["content"][0]["type"] == "text"
            assert messages[0]["content"][1]["type"] == "input_audio"
            assert "input_audio" in messages[0]["content"][1]
            assert messages[0]["content"][1]["input_audio"]["format"] == "ogg"
    
    def test_default_model(self, tmp_path):
        """Test that default model is used when not specified."""
        audio_path = tmp_path / "test.ogg"
        audio_path.write_bytes(b"fake audio data")
        
        with patch("sr_transcription.api._openrouter_request") as mock_request:
            mock_request.return_value = "transcript"
            
            transcribe_with_openrouter(
                api_key="test-key",
                audio_path=audio_path,
            )
            
            call_args = mock_request.call_args
            assert call_args[0][1] == DEFAULT_MODEL


class TestTranscribeAndSave:
    """Test transcribe_and_save function."""
    
    def test_successful_save(self, tmp_path):
        """Test that valid transcript is saved to file."""
        audio_path = tmp_path / "input.ogg"
        audio_path.write_bytes(b"fake audio data")
        output_path = tmp_path / "output" / "transcript.txt"
        
        with patch("sr_transcription.api.transcribe_with_openrouter") as mock_transcribe:
            mock_transcribe.return_value = "Valid transcript content."
            
            transcribe_and_save(
                api_key="test-key",
                audio_path=audio_path,
                output_path=output_path,
            )
            
            assert output_path.exists()
            assert output_path.read_text() == "Valid transcript content."
    
    def test_creates_parent_directories(self, tmp_path):
        """Test that parent directories are created if needed."""
        audio_path = tmp_path / "input.ogg"
        audio_path.write_bytes(b"fake audio data")
        output_path = tmp_path / "deep" / "nested" / "dir" / "transcript.txt"
        
        with patch("sr_transcription.api.transcribe_with_openrouter") as mock_transcribe:
            mock_transcribe.return_value = "Transcript."
            
            transcribe_and_save(
                api_key="test-key",
                audio_path=audio_path,
                output_path=output_path,
            )
            
            assert output_path.exists()
    
    def test_empty_transcript_raises(self, tmp_path):
        """Test that empty transcript raises RuntimeError."""
        audio_path = tmp_path / "input.ogg"
        audio_path.write_bytes(b"fake audio data")
        output_path = tmp_path / "output.txt"
        
        with patch("sr_transcription.api.transcribe_with_openrouter") as mock_transcribe:
            mock_transcribe.return_value = ""
            
            with pytest.raises(RuntimeError, match="empty"):
                transcribe_and_save(
                    api_key="test-key",
                    audio_path=audio_path,
                    output_path=output_path,
                )
            
            # Verify no file was created
            assert not output_path.exists()
    
    def test_whitespace_only_transcript_raises(self, tmp_path):
        """Test that whitespace-only transcript raises RuntimeError."""
        audio_path = tmp_path / "input.ogg"
        audio_path.write_bytes(b"fake audio data")
        output_path = tmp_path / "output.txt"
        
        with patch("sr_transcription.api.transcribe_with_openrouter") as mock_transcribe:
            mock_transcribe.return_value = "   \n\t  "
            
            with pytest.raises(RuntimeError, match="empty"):
                transcribe_and_save(
                    api_key="test-key",
                    audio_path=audio_path,
                    output_path=output_path,
                )
            
            assert not output_path.exists()
    
    def test_newline_only_transcript_raises(self, tmp_path):
        """Test that newline-only transcript raises RuntimeError."""
        audio_path = tmp_path / "input.ogg"
        audio_path.write_bytes(b"fake audio data")
        output_path = tmp_path / "output.txt"
        
        with patch("sr_transcription.api.transcribe_with_openrouter") as mock_transcribe:
            mock_transcribe.return_value = "\n\n\n"
            
            with pytest.raises(RuntimeError, match="empty"):
                transcribe_and_save(
                    api_key="test-key",
                    audio_path=audio_path,
                    output_path=output_path,
                )
            
            assert not output_path.exists()


class TestFormatValidation:
    """Test audio format validation."""
    
    @pytest.mark.parametrize("ext", ["ogg", "mp3", "wav", "m4a", "aac", "flac", "aiff"])
    def test_valid_formats(self, tmp_path, ext):
        """Test that all supported formats are accepted."""
        audio_path = tmp_path / f"test.{ext}"
        audio_path.write_bytes(b"fake audio data")
        
        with patch("sr_transcription.api._openrouter_request") as mock_request:
            mock_request.return_value = "transcript"
            
            result = transcribe_with_openrouter(
                api_key="test-key",
                audio_path=audio_path,
            )
            
            assert result == "transcript"
    
    @pytest.mark.parametrize("ext", ["txt", "mp4", "avi", "pdf", "jpg"])
    def test_invalid_formats_raise(self, tmp_path, ext):
        """Test that invalid formats raise ValueError."""
        audio_path = tmp_path / f"test.{ext}"
        audio_path.write_bytes(b"fake data")
        
        with pytest.raises(ValueError, match="Unsupported audio format"):
            transcribe_with_openrouter(
                api_key="test-key",
                audio_path=audio_path,
            )
    
    def test_error_shows_supported_formats(self, tmp_path):
        """Test that error message lists supported formats."""
        audio_path = tmp_path / "test.xyz"
        audio_path.write_bytes(b"fake data")
        
        with pytest.raises(ValueError) as exc_info:
            transcribe_with_openrouter(
                api_key="test-key",
                audio_path=audio_path,
            )
        
        error_msg = str(exc_info.value)
        assert "ogg" in error_msg
        assert "mp3" in error_msg
        assert "wav" in error_msg
    
    def test_case_insensitive_extension(self, tmp_path):
        """Test that extensions are case-insensitive."""
        audio_path = tmp_path / "test.OGG"
        audio_path.write_bytes(b"fake audio data")
        
        with patch("sr_transcription.api._openrouter_request") as mock_request:
            mock_request.return_value = "transcript"
            
            result = transcribe_with_openrouter(
                api_key="test-key",
                audio_path=audio_path,
            )
            
            assert result == "transcript"


class TestConstants:
    """Test package constants."""
    
    def test_default_model_constant(self):
        """Test that DEFAULT_MODEL is a non-empty string."""
        assert isinstance(DEFAULT_MODEL, str)
        assert len(DEFAULT_MODEL) > 0
        assert "/" in DEFAULT_MODEL  # Should be in format "provider/model"
    
    def test_prompt_constant(self):
        """Test that TRANSCRIBE_PROMPT is a non-empty string with Arabic mention."""
        assert isinstance(TRANSCRIBE_PROMPT, str)
        assert len(TRANSCRIBE_PROMPT) > 0
        assert "Arabic" in TRANSCRIBE_PROMPT
        assert "verbatim" in TRANSCRIBE_PROMPT.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
