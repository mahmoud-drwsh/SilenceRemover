"""Unit tests for openrouter_transport package.

Tests cover HTTP client with retry logic, response parsing, error handling,
and logging. All API calls are mocked.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import re

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

import pytest

from openrouter_transport import request
from openrouter_transport.client import (
    _parse_retry_seconds_from_error,
    _status_code_from_error,
    _messages_to_log_text,
    _append_openrouter_log,
    _append_openrouter_error_log,
)


class TestRequestSuccessful:
    """Test successful request scenarios."""
    
    def test_successful_request_returns_content(self):
        """Test that successful API call returns response content."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test response"
        
        with patch("openrouter_transport.client.OpenRouter") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.chat.send.return_value = mock_response
            
            result = request(
                api_key="test-key",
                model="test-model",
                messages=[{"role": "user", "content": "Hello"}],
            )
            
            assert result == "Test response"
    
    def test_response_with_whitespace_is_normalized(self):
        """Test that response content is stripped of whitespace."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "  Test response  \n  "
        
        with patch("openrouter_transport.client.OpenRouter") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.chat.send.return_value = mock_response
            
            result = request(
                api_key="test-key",
                model="test-model",
                messages=[{"role": "user", "content": "Hello"}],
            )
            
            assert result == "Test response"
    
    def test_empty_response_returns_empty_string(self):
        """Test that empty response returns empty string after logging."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""
        
        with patch("openrouter_transport.client.OpenRouter") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.chat.send.return_value = mock_response
            
            with patch("builtins.print") as mock_print:
                result = request(
                    api_key="test-key",
                    model="test-model",
                    messages=[{"role": "user", "content": "Hello"}],
                )
                
                assert result == ""
                mock_print.assert_called_once()
                assert "empty" in mock_print.call_args[0][0].lower()


class TestRequestRetryLogic:
    """Test retry logic for various HTTP errors."""
    
    def test_http_429_retries_with_delay(self):
        """Test that 429 rate limit triggers retry."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Success"
        
        error = Exception("Rate limited")
        error.response = MagicMock()
        error.response.status_code = 429
        
        with patch("openrouter_transport.client.OpenRouter") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            # First call raises, second succeeds
            mock_client.chat.send.side_effect = [error, mock_response]
            
            with patch("time.sleep") as mock_sleep:
                result = request(
                    api_key="test-key",
                    model="test-model",
                    messages=[{"role": "user", "content": "Hello"}],
                )
                
                assert result == "Success"
                assert mock_sleep.called  # Should have slept before retry
                assert mock_client.chat.send.call_count == 2
    
    def test_http_500_retries(self):
        """Test that 500 server error triggers retry."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Success"
        
        error = Exception("Server error")
        error.response = MagicMock()
        error.response.status_code = 500
        
        with patch("openrouter_transport.client.OpenRouter") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.chat.send.side_effect = [error, mock_response]
            
            with patch("time.sleep") as mock_sleep:
                result = request(
                    api_key="test-key",
                    model="test-model",
                    messages=[{"role": "user", "content": "Hello"}],
                )
                
                assert result == "Success"
                assert mock_client.chat.send.call_count == 2
    
    def test_http_400_fails_immediately_no_retry(self):
        """Test that 400 client error fails immediately without retry."""
        error = Exception("Bad request")
        error.response = MagicMock()
        error.response.status_code = 400
        
        with patch("openrouter_transport.client.OpenRouter") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.chat.send.side_effect = error
            
            with pytest.raises(Exception):
                request(
                    api_key="test-key",
                    model="test-model",
                    messages=[{"role": "user", "content": "Hello"}],
                )
            
            # Should only be called once (no retries)
            assert mock_client.chat.send.call_count == 1
    
    def test_max_attempts_exhausted_raises(self):
        """Test that all retries exhausted raises final exception."""
        error = Exception("Persistent error")
        error.response = MagicMock()
        error.response.status_code = 429
        
        with patch("openrouter_transport.client.OpenRouter") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.chat.send.side_effect = error
            
            with pytest.raises(Exception, match="Persistent error"):
                request(
                    api_key="test-key",
                    model="test-model",
                    messages=[{"role": "user", "content": "Hello"}],
                    max_attempts=3,
                )
            
            assert mock_client.chat.send.call_count == 3
    
    def test_keyboard_interrupt_not_retried(self):
        """Test that KeyboardInterrupt propagates immediately without retry."""
        with patch("openrouter_transport.client.OpenRouter") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.chat.send.side_effect = KeyboardInterrupt()
            
            with pytest.raises(KeyboardInterrupt):
                request(
                    api_key="test-key",
                    model="test-model",
                    messages=[{"role": "user", "content": "Hello"}],
                )
            
            # Should only be called once
            assert mock_client.chat.send.call_count == 1


class TestRetryDelayParsing:
    """Test parsing retry delays from error messages."""
    
    def test_parse_retry_in_seconds_format(self):
        """Test parsing 'retry in 5s' format."""
        error = Exception("Please retry in 10s")
        result = _parse_retry_seconds_from_error(error)
        assert result == 10.0
    
    def test_parse_retry_delay_colon_format(self):
        """Test parsing 'retryDelay: 15' format."""
        error = Exception("retryDelay: 15")
        result = _parse_retry_seconds_from_error(error)
        assert result == 15.0
    
    def test_parse_retry_delay_quoted_format(self):
        """Test parsing 'retryDelay: '15s'' format (single quotes)."""
        error = Exception("retryDelay: '15s'")
        result = _parse_retry_seconds_from_error(error)
        assert result == 15.0
    
    def test_parse_no_match_returns_default(self):
        """Test that no match returns 6.0 default."""
        error = Exception("Some random error message")
        result = _parse_retry_seconds_from_error(error)
        assert result == 6.0
    
    def test_parse_float_seconds(self):
        """Test parsing float seconds like 'retry in 5.5s'."""
        error = Exception("Please retry in 5.5s")
        result = _parse_retry_seconds_from_error(error)
        assert result == 5.5


class TestStatusCodeExtraction:
    """Test extracting HTTP status codes from errors."""
    
    def test_extract_from_response_attribute(self):
        """Test extracting status code from error.response.status_code."""
        error = Exception("Error")
        error.response = MagicMock()
        error.response.status_code = 429
        
        result = _status_code_from_error(error)
        assert result == 429
    
    def test_extract_no_response_attribute(self):
        """Test that missing response attribute returns None."""
        error = Exception("Error")
        
        result = _status_code_from_error(error)
        assert result is None
    
    def test_extract_no_status_code_attribute(self):
        """Test that missing status_code attribute returns None."""
        error = Exception("Error")
        # Create a response object without status_code attribute
        class FakeResponse:
            pass
        error.response = FakeResponse()
        
        result = _status_code_from_error(error)
        assert result is None


class TestMessageLoggingSanitization:
    """Test message sanitization for logging."""
    
    def test_simple_text_message(self):
        """Test that simple text messages pass through unchanged."""
        messages = [{"role": "user", "content": "Hello world"}]
        result = _messages_to_log_text(messages)
        assert "Hello world" in result
    
    def test_audio_content_sanitized(self):
        """Test that audio content is sanitized to metadata."""
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Transcribe this"},
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": "dGVzdA==",  # base64 "test"
                        "format": "ogg"
                    }
                }
            ]
        }]
        
        result = _messages_to_log_text(messages)
        assert "dGVzdA==" not in result  # Base64 should be removed
        assert "[audio, format=ogg, base64_length=8]" in result
    
    def test_multiple_messages(self):
        """Test handling multiple messages."""
        messages = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "Second message"},
        ]
        result = _messages_to_log_text(messages)
        assert "First message" in result
        assert "Second message" in result


class TestLoggingFunctions:
    """Test log file creation."""
    
    def test_successful_log_creation(self, tmp_path):
        """Test that successful requests create log files."""
        log_dir = tmp_path
        
        _append_openrouter_log(
            log_dir=log_dir,
            model="test-model",
            input_text="Test input",
            output_text="Test output",
        )
        
        # Check that log files were created
        logs_dir = log_dir / "logs"
        assert logs_dir.exists()
        
        # Should have request and response files
        files = list(logs_dir.glob("*_request.txt"))
        assert len(files) == 1
        
        files = list(logs_dir.glob("*_response.txt"))
        assert len(files) == 1
        
        # Verify content
        request_file = list(logs_dir.glob("*_request.txt"))[0]
        content = request_file.read_text()
        assert "MODEL: test-model" in content
        assert "Test input" in content
    
    def test_error_log_creation(self, tmp_path):
        """Test that failed requests create error log files."""
        log_dir = tmp_path
        
        _append_openrouter_error_log(
            log_dir=log_dir,
            model="test-model",
            input_text="Test input",
            attempt=2,
            error_kind="rate_limited",
            error_text="Too many requests",
        )
        
        # Check that error log was created
        errors_dir = log_dir / "logs" / "errors"
        assert errors_dir.exists()
        
        files = list(errors_dir.glob("*.txt"))
        assert len(files) == 1
        
        # Verify content
        content = files[0].read_text()
        assert "MODEL: test-model" in content
        assert "rate_limited" in content
        assert "Too many requests" in content


class TestMaxInputTokensFallback:
    """Test special handling for max_input_tokens rejection."""
    
    def test_max_input_tokens_rejection_retries_without_param(self):
        """Test that max_input_tokens rejection triggers retry without the param."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Success"
        
        error = Exception("max_input_tokens is not supported")
        error.response = MagicMock()
        error.response.status_code = 400
        
        with patch("openrouter_transport.client.OpenRouter") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.chat.send.side_effect = [error, mock_response]
            
            result = request(
                api_key="test-key",
                model="test-model",
                messages=[{"role": "user", "content": "Hello"}],
                max_input_tokens=1000,
            )
            
            assert result == "Success"
            # Should have been called twice
            assert mock_client.chat.send.call_count == 2
            
            # Second call should not have max_input_tokens
            second_call = mock_client.chat.send.call_args_list[1]
            assert "max_input_tokens" not in second_call.kwargs
    
    def test_max_input_tokens_permanent_failure(self):
        """Test that persistent max_input_tokens rejection eventually fails."""
        error = Exception("max_input_tokens is not supported")
        error.response = MagicMock()
        error.response.status_code = 400
        
        with patch("openrouter_transport.client.OpenRouter") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.chat.send.side_effect = error
            
            with pytest.raises(Exception):
                request(
                    api_key="test-key",
                    model="test-model",
                    messages=[{"role": "user", "content": "Hello"}],
                    max_input_tokens=1000,
                    max_attempts=2,
                )


class TestListContentHandling:
    """Test handling of list-type response content."""
    
    def test_list_content_aggregated(self):
        """Test that list content is aggregated into string."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = [
            {"type": "text", "text": "First part. "},
            {"type": "text", "text": "Second part."},
        ]
        
        with patch("openrouter_transport.client.OpenRouter") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.chat.send.return_value = mock_response
            
            result = request(
                api_key="test-key",
                model="test-model",
                messages=[{"role": "user", "content": "Hello"}],
            )
            
            assert result == "First part. Second part."


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
