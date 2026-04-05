"""Unit tests for sr_title package.

Tests cover the two-phase title generation flow with candidate generation,
scoring, and selection. All OpenRouter API calls are mocked.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

import pytest

from sr_title import (
    DEFAULT_MODEL,
    TITLE_CANDIDATES_PROMPT_TEMPLATE,
    TITLE_CANDIDATES_SCORE_PROMPT_TEMPLATE,
    TITLE_PROMPT_TEMPLATE,
    generate_title_from_transcript,
    generate_title_with_openrouter,
)
from sr_title.api import (
    _coerce_score_0_10,
    _parse_title_candidates_json,
    _parse_title_evaluation_json,
    _select_title_by_scores,
    _selection_sort_key,
    _strip_optional_json_fences,
)


class TestStripJsonFences:
    """Test JSON fence stripping utility."""
    
    def test_strip_json_code_fence(self):
        """Test stripping ```json ... ``` fences."""
        input_str = '```json\n["title1", "title2"]\n```'
        result = _strip_optional_json_fences(input_str)
        assert result == '["title1", "title2"]'
    
    def test_strip_generic_code_fence(self):
        """Test stripping generic ``` fences."""
        input_str = '```\n{"key": "value"}\n```'
        result = _strip_optional_json_fences(input_str)
        assert result == '{"key": "value"}'
    
    def test_no_fences_unchanged(self):
        """Test that string without fences is unchanged."""
        input_str = '["title1", "title2"]'
        result = _strip_optional_json_fences(input_str)
        assert result == '["title1", "title2"]'


class TestParseTitleCandidatesJson:
    """Test candidate JSON parsing."""
    
    def test_parse_valid_array(self):
        """Test parsing valid JSON array."""
        raw = '["Title One", "Title Two", "Title Three"]'
        result = _parse_title_candidates_json(raw, expected=3)
        assert result == ["Title One", "Title Two", "Title Three"]
    
    def test_parse_with_markdown_fences(self):
        """Test parsing array with markdown fences."""
        raw = '```json\n["Title One", "Title Two"]\n```'
        result = _parse_title_candidates_json(raw, expected=2)
        assert result == ["Title One", "Title Two"]
    
    def test_parse_extracts_array_from_text(self):
        """Test extraction when array is embedded in text."""
        raw = 'Here are the titles: ["Title One", "Title Two"] Hope these help!'
        result = _parse_title_candidates_json(raw, expected=2)
        assert result == ["Title One", "Title Two"]
    
    def test_parse_deduplicates_candidates(self):
        """Test that duplicate candidates are deduplicated."""
        raw = '["Same Title", "Same Title", "Different Title"]'
        result = _parse_title_candidates_json(raw, expected=3)
        assert len(result) == 2
        assert "Same Title" in result
        assert "Different Title" in result
    
    def test_parse_rejects_newlines_in_candidates(self):
        """Test that candidates with newlines are rejected."""
        # Use escaped newline in JSON string
        raw = '["Valid Title", "Invalid\\nTitle", "Another"]'
        with pytest.raises(RuntimeError, match="newline"):
            _parse_title_candidates_json(raw, expected=3)
    
    def test_parse_rejects_non_string_elements(self):
        """Test that non-string elements are rejected."""
        raw = '["Valid", 123, "Another"]'
        with pytest.raises(RuntimeError):
            _parse_title_candidates_json(raw, expected=3)
    
    def test_parse_handles_count_mismatch(self):
        """Test handling of expected vs actual count mismatch."""
        raw = '["Title One", "Title Two"]'
        # Requested 3 but got 2 - should warn but proceed
        with patch("builtins.print") as mock_print:
            result = _parse_title_candidates_json(raw, expected=3)
            assert len(result) == 2
            mock_print.assert_called_once()
    
    def test_parse_empty_array_raises(self):
        """Test that empty array raises RuntimeError."""
        raw = '[]'
        with pytest.raises(RuntimeError):
            _parse_title_candidates_json(raw, expected=3)
    
    def test_parse_invalid_json_raises(self):
        """Test that invalid JSON raises RuntimeError."""
        raw = 'not valid json'
        with pytest.raises(RuntimeError):
            _parse_title_candidates_json(raw, expected=3)
    
    def test_parse_non_array_raises(self):
        """Test that non-array JSON raises RuntimeError."""
        raw = '{"titles": ["one", "two"]}'
        with pytest.raises(RuntimeError):
            _parse_title_candidates_json(raw, expected=2)


class TestCoerceScore:
    """Test score coercion utility."""
    
    def test_valid_integer(self):
        """Test that valid integers pass through."""
        assert _coerce_score_0_10("verbatim_score", 0, 5) == 5
        assert _coerce_score_0_10("correctness_score", 0, 0) == 0
        assert _coerce_score_0_10("verbatim_score", 0, 10) == 10
    
    def test_integer_float_accepted(self):
        """Test that integer-valued floats are accepted."""
        assert _coerce_score_0_10("verbatim_score", 0, 5.0) == 5
        assert _coerce_score_0_10("correctness_score", 0, 10.0) == 10
    
    def test_non_integer_float_rejected(self):
        """Test that non-integer floats are rejected."""
        with pytest.raises(RuntimeError, match="expected integer score"):
            _coerce_score_0_10("verbatim_score", 0, 5.5)
    
    def test_boolean_rejected(self):
        """Test that boolean values are rejected."""
        with pytest.raises(RuntimeError, match="boolean is not a valid score"):
            _coerce_score_0_10("verbatim_score", 0, True)
        with pytest.raises(RuntimeError, match="boolean is not a valid score"):
            _coerce_score_0_10("correctness_score", 1, False)
    
    def test_string_rejected(self):
        """Test that string values are rejected."""
        with pytest.raises(RuntimeError, match="expected number"):
            _coerce_score_0_10("verbatim_score", 0, "5")
    
    def test_out_of_range_rejected(self):
        """Test that out-of-range values are rejected."""
        with pytest.raises(RuntimeError, match="out of allowed"):
            _coerce_score_0_10("verbatim_score", 0, -1)
        with pytest.raises(RuntimeError, match="out of allowed"):
            _coerce_score_0_10("correctness_score", 0, 11)
    
    def test_none_rejected(self):
        """Test that None is rejected."""
        with pytest.raises(RuntimeError, match="expected number"):
            _coerce_score_0_10("verbatim_score", 0, None)


class TestParseTitleEvaluationJson:
    """Test evaluation JSON parsing."""
    
    def test_parse_valid_evaluations(self):
        """Test parsing valid evaluations array."""
        raw = '{"evaluations": [{"verbatim_score": 10, "correctness_score": 9}, {"verbatim_score": 8, "correctness_score": 7}]}'
        result = _parse_title_evaluation_json(raw, n=2)
        assert result == [(10, 9), (8, 7)]
    
    def test_parse_with_markdown_fences(self):
        """Test parsing with markdown fences."""
        raw = '```json\n{"evaluations": [{"verbatim_score": 10, "correctness_score": 10}]}\n```'
        result = _parse_title_evaluation_json(raw, n=1)
        assert result == [(10, 10)]
    
    def test_parse_extracts_object_from_text(self):
        """Test extraction when object is embedded in text."""
        raw = 'Here is the evaluation: {"evaluations": [{"verbatim_score": 5, "correctness_score": 5}]} Thanks!'
        result = _parse_title_evaluation_json(raw, n=1)
        assert result == [(5, 5)]
    
    def test_parse_rejects_count_mismatch(self):
        """Test that count mismatch raises RuntimeError."""
        raw = '{"evaluations": [{"verbatim_score": 10, "correctness_score": 10}]}'
        with pytest.raises(RuntimeError, match="expected 2 evaluations, got 1"):
            _parse_title_evaluation_json(raw, n=2)
    
    def test_parse_rejects_missing_evaluations_key(self):
        """Test that missing evaluations key raises RuntimeError."""
        raw = '{"scores": [{"verbatim_score": 10}]}'
        with pytest.raises(RuntimeError, match="evaluations"):
            _parse_title_evaluation_json(raw, n=1)
    
    def test_parse_rejects_missing_score_fields(self):
        """Test that missing score fields raise RuntimeError."""
        raw = '{"evaluations": [{"verbatim_score": 10}]}'
        with pytest.raises(RuntimeError, match="correctness_score"):
            _parse_title_evaluation_json(raw, n=1)
    
    def test_parse_rejects_invalid_score_types(self):
        """Test that invalid score types raise RuntimeError."""
        raw = '{"evaluations": [{"verbatim_score": true, "correctness_score": 10}]}'
        with pytest.raises(RuntimeError, match="boolean"):
            _parse_title_evaluation_json(raw, n=1)
    
    def test_parse_rejects_non_object(self):
        """Test that non-object JSON raises RuntimeError."""
        raw = '[{"verbatim_score": 10, "correctness_score": 10}]'
        with pytest.raises(RuntimeError, match="JSON object"):
            _parse_title_evaluation_json(raw, n=1)


class TestSelectionSortKey:
    """Test selection sort key for tie-breaking."""
    
    def test_position_in_transcript(self):
        """Test that position in transcript affects sort key."""
        transcript = "start title1 middle title2 end"
        candidate = "title1"
        index = 0
        
        key = _selection_sort_key(transcript, candidate, index)
        # title1 appears at position 6
        assert key[0] == 6  # position
    
    def test_length_penalty_ideal_length(self):
        """Test length penalty for ideal length (20-80 chars)."""
        transcript = "some text "
        candidate = "x" * 50  # 50 chars - within ideal range
        
        key = _selection_sort_key(transcript, candidate, 0)
        # Length 50 is within 20-80, so penalty should be 0
        assert key[1] == 0
    
    def test_length_penalty_too_short(self):
        """Test length penalty for short titles (<20)."""
        transcript = "some text "
        candidate = "x" * 10  # 10 chars - too short
        
        key = _selection_sort_key(transcript, candidate, 0)
        # Penalty = 20 - 10 = 10
        assert key[1] == 10
    
    def test_length_penalty_too_long(self):
        """Test length penalty for long titles (>80)."""
        transcript = "some text "
        candidate = "x" * 100  # 100 chars - too long
        
        key = _selection_sort_key(transcript, candidate, 0)
        # Penalty = 100 - 80 = 20
        assert key[1] == 20
    
    def test_generation_index_tiebreaker(self):
        """Test that generation index is final tiebreaker."""
        transcript = "text here"
        candidate = "title"
        
        key0 = _selection_sort_key(transcript, candidate, 0)
        key1 = _selection_sort_key(transcript, candidate, 1)
        
        # Same position and length, but different index
        assert key0[0] == key1[0]  # position
        assert key0[1] == key1[1]  # length penalty
        assert key0[2] == 0  # index 0
        assert key1[2] == 1  # index 1


class TestSelectTitleByScores:
    """Test title selection by scores."""
    
    def test_select_highest_combined_score(self):
        """Test that candidate with highest combined score wins."""
        transcript = "text title1 more title2"
        candidates = ["title1", "title2"]
        scores = [(10, 10), (8, 8)]  # 20 vs 16
        
        result = _select_title_by_scores(transcript, candidates, scores)
        assert result == "title1"  # Higher score
    
    def test_tiebreak_by_position(self):
        """Test tie-breaking by position in transcript."""
        transcript = "title1 comes first then title2"
        candidates = ["title1", "title2"]
        scores = [(10, 5), (10, 5)]  # Same combined score (15)
        
        result = _select_title_by_scores(transcript, candidates, scores)
        assert result == "title1"  # Appears first
    
    def test_tiebreak_by_length(self):
        """Test tie-breaking by length penalty."""
        transcript = "text here and here"
        candidates = ["x" * 100, "y" * 50]  # Both at same position
        scores = [(10, 5), (10, 5)]  # Same scores
        
        result = _select_title_by_scores(transcript, candidates, scores)
        assert result == "y" * 50  # 50 is ideal, 100 has penalty
    
    def test_selects_single_candidate(self):
        """Test that single candidate is selected."""
        transcript = "text with title here"
        candidates = ["title"]
        scores = [(10, 10)]
        
        result = _select_title_by_scores(transcript, candidates, scores)
        assert result == "title"
    
    def test_returns_empty_string_for_empty_candidates(self):
        """Test that empty candidates list returns empty string."""
        result = _select_title_by_scores("transcript", [], [])
        assert result == ""


class TestGenerateTitleWithOpenRouter:
    """Test end-to-end title generation flow."""
    
    def test_happy_path_two_phase_flow(self):
        """Test complete two-phase generation flow."""
        transcript = "Arabic text here with title content"
        
        # Mock Phase 1 (candidate generation)
        phase1_response = '["العنوان الأول", "عنوان ثانٍ", "عنوان ثالث"]'
        
        # Mock Phase 2 (scoring)
        phase2_response = '{"evaluations": [{"verbatim_score": 10, "correctness_score": 10}, {"verbatim_score": 8, "correctness_score": 9}, {"verbatim_score": 9, "correctness_score": 8}]}'
        
        with patch("sr_title.api.openrouter_request") as mock_request:
            mock_request.side_effect = [phase1_response, phase2_response]
            
            result = generate_title_with_openrouter(
                api_key="test-key",
                transcript=transcript,
            )
            
            # Should select first candidate (score 20 > 17 > 17)
            assert result == "العنوان الأول"
            assert mock_request.call_count == 2
    
    def test_empty_transcript_raises(self):
        """Test that empty transcript raises before API calls."""
        with pytest.raises(RuntimeError, match="empty"):
            generate_title_with_openrouter(
                api_key="test-key",
                transcript="",
            )
    
    def test_whitespace_only_transcript_raises(self):
        """Test that whitespace-only transcript raises."""
        with pytest.raises(RuntimeError, match="empty"):
            generate_title_with_openrouter(
                api_key="test-key",
                transcript="   \n\t  ",
            )
    
    def test_api_error_in_phase1_raises(self):
        """Test that Phase 1 API error propagates."""
        with patch("sr_title.api.openrouter_request") as mock_request:
            mock_request.side_effect = RuntimeError("API failed")
            
            with pytest.raises(RuntimeError, match="API failed"):
                generate_title_with_openrouter(
                    api_key="test-key",
                    transcript="Some Arabic text",
                )
    
    def test_api_error_in_phase2_raises(self):
        """Test that Phase 2 API error propagates."""
        phase1_response = '["Title One", "Title Two"]'
        
        with patch("sr_title.api.openrouter_request") as mock_request:
            mock_request.side_effect = [phase1_response, RuntimeError("Phase 2 failed")]
            
            with pytest.raises(RuntimeError, match="Phase 2 failed"):
                generate_title_with_openrouter(
                    api_key="test-key",
                    transcript="Some text",
                )
    
    def test_correct_model_passed(self):
        """Test that correct model is passed to API calls."""
        with patch("sr_title.api.openrouter_request") as mock_request:
            mock_request.side_effect = ['["Title"]', '{"evaluations": [{"verbatim_score": 10, "correctness_score": 10}]}']
            
            generate_title_with_openrouter(
                api_key="test-key",
                transcript="Some text",
                model="custom-model",
            )
            
            # Both calls should use custom model
            assert mock_request.call_args_list[0][0][1] == "custom-model"
            assert mock_request.call_args_list[1][0][1] == "custom-model"
    
    def test_default_model_used(self):
        """Test that default model is used when not specified."""
        with patch("sr_title.api.openrouter_request") as mock_request:
            mock_request.side_effect = ['["Title"]', '{"evaluations": [{"verbatim_score": 10, "correctness_score": 10}]}']
            
            generate_title_with_openrouter(
                api_key="test-key",
                transcript="Some text",
            )
            
            # Should use DEFAULT_MODEL
            assert mock_request.call_args_list[0][0][1] == DEFAULT_MODEL
    
    def test_prompts_contain_transcript(self):
        """Test that prompts include the transcript."""
        with patch("sr_title.api.openrouter_request") as mock_request:
            mock_request.side_effect = ['["Title"]', '{"evaluations": [{"verbatim_score": 10, "correctness_score": 10}]}']
            
            test_transcript = "Test transcript content here"
            generate_title_with_openrouter(
                api_key="test-key",
                transcript=test_transcript,
            )
            
            # Both prompts should contain transcript
            call_args_list = mock_request.call_args_list
            messages1 = call_args_list[0][0][2]
            messages2 = call_args_list[1][0][2]
            
            assert any(test_transcript in str(msg) for msg in messages1)
            assert any(test_transcript in str(msg) for msg in messages2)


class TestGenerateTitleFromTranscript:
    """Test file-based title generation."""
    
    def test_successful_file_operations(self, tmp_path):
        """Test reading transcript and writing title."""
        transcript_path = tmp_path / "transcript.txt"
        transcript_path.write_text("Arabic text content", encoding="utf-8")
        output_path = tmp_path / "title.txt"
        
        with patch("sr_title.api.generate_title_with_openrouter") as mock_generate:
            mock_generate.return_value = "Generated Title"
            
            generate_title_from_transcript(
                api_key="test-key",
                transcript_path=transcript_path,
                output_path=output_path,
            )
            
            assert output_path.exists()
            assert output_path.read_text(encoding="utf-8") == "Generated Title"
    
    def test_creates_parent_directories(self, tmp_path):
        """Test that output directory is created if needed."""
        transcript_path = tmp_path / "transcript.txt"
        transcript_path.write_text("Content", encoding="utf-8")
        output_path = tmp_path / "deep" / "nested" / "title.txt"
        
        with patch("sr_title.api.generate_title_with_openrouter") as mock_generate:
            mock_generate.return_value = "Title"
            
            generate_title_from_transcript(
                api_key="test-key",
                transcript_path=transcript_path,
                output_path=output_path,
            )
            
            assert output_path.exists()
    
    def test_empty_file_raises(self, tmp_path):
        """Test that empty transcript file raises."""
        # Create an empty file
        transcript_path = tmp_path / "empty.txt"
        transcript_path.write_text("", encoding="utf-8")
        
        with pytest.raises(RuntimeError, match="empty"):
            generate_title_from_transcript(
                api_key="test-key",
                transcript_path=transcript_path,
                output_path=tmp_path / "title.txt",
            )


class TestConstants:
    """Test package constants."""
    
    def test_default_model_constant(self):
        """Test that DEFAULT_MODEL is set correctly."""
        assert isinstance(DEFAULT_MODEL, str)
        assert len(DEFAULT_MODEL) > 0
        assert "/" in DEFAULT_MODEL
    
    def test_candidates_prompt_template(self):
        """Test that candidates prompt template exists."""
        assert isinstance(TITLE_CANDIDATES_PROMPT_TEMPLATE, str)
        assert len(TITLE_CANDIDATES_PROMPT_TEMPLATE) > 0
        assert "transcript" in TITLE_CANDIDATES_PROMPT_TEMPLATE.lower()
        assert "{candidate_count}" in TITLE_CANDIDATES_PROMPT_TEMPLATE
    
    def test_score_prompt_template(self):
        """Test that score prompt template exists."""
        assert isinstance(TITLE_CANDIDATES_SCORE_PROMPT_TEMPLATE, str)
        assert len(TITLE_CANDIDATES_SCORE_PROMPT_TEMPLATE) > 0
        assert "{transcript}" in TITLE_CANDIDATES_SCORE_PROMPT_TEMPLATE
        assert "{candidates_json}" in TITLE_CANDIDATES_SCORE_PROMPT_TEMPLATE
    
    def test_legacy_prompt_template(self):
        """Test that legacy prompt template exists for backward compatibility."""
        assert isinstance(TITLE_PROMPT_TEMPLATE, str)
        assert len(TITLE_PROMPT_TEMPLATE) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
