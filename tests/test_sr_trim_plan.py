"""Integration tests for sr_trim_plan package.

Tests run against generated fixture videos. Generate fixtures with:
    python tests/generate_fixtures.py
"""

import sys
from pathlib import Path

import pytest

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

from sr_trim_plan import build_trim_plan, TrimPlan
from src.core.constants import (
    NON_TARGET_MIN_DURATION_SEC,
    NON_TARGET_NOISE_THRESHOLD_DB,
    NON_TARGET_PAD_SEC,
    SNIPPET_MAX_DURATION_SEC,
    TARGET_SEARCH_BASE_PADDING_SEC,
    TARGET_SEARCH_HIGH_DB,
    TARGET_SEARCH_LOW_DB,
    TARGET_SEARCH_MIN_SILENCE_LEN_SEC,
)


def validate_trim_plan(plan: TrimPlan, video_path: Path) -> None:
    """Validate a TrimPlan has valid structure and invariants."""
    # Basic field presence
    assert plan.mode in ("target", "non_target"), f"Invalid mode: {plan.mode}"
    assert plan.input_duration_sec > 0, f"Invalid duration: {plan.input_duration_sec}"
    assert plan.resulting_length_sec >= 0, f"Invalid resulting length: {plan.resulting_length_sec}"
    assert plan.resolved_noise_threshold < 0, f"Noise threshold should be negative dB: {plan.resolved_noise_threshold}"
    assert plan.resolved_min_duration > 0, f"Invalid min_duration: {plan.resolved_min_duration}"
    assert plan.resolved_pad_sec >= 0, f"Invalid pad_sec: {plan.resolved_pad_sec}"
    
    # Segment validation
    assert len(plan.segments_to_keep) > 0, "Must have at least one segment to keep"
    
    total_length = 0.0
    prev_end = -1.0
    
    for i, (start, end) in enumerate(plan.segments_to_keep):
        # Basic validity
        assert start >= 0, f"Segment {i}: negative start time {start}"
        assert end > start, f"Segment {i}: invalid interval {start} >= {end}"
        assert end <= plan.input_duration_sec + 0.001, f"Segment {i}: end {end} exceeds duration {plan.input_duration_sec}"
        
        # No overlaps
        if i > 0:
            assert start >= prev_end - 0.001, f"Segment {i}: overlaps with previous (starts at {start}, prev ends at {prev_end})"
        
        total_length += (end - start)
        prev_end = end
    
    # Resulting length should match sum of segments
    assert abs(total_length - plan.resulting_length_sec) < 0.001, \
        f"Resulting length mismatch: sum={total_length:.3f}, plan={plan.resulting_length_sec:.3f}"
    
    # Target mode specific
    if plan.mode == "target" and plan.target_length is not None:
        assert plan.resolved_min_duration == TARGET_SEARCH_MIN_SILENCE_LEN_SEC
        assert plan.resolved_pad_sec >= TARGET_SEARCH_BASE_PADDING_SEC
        assert TARGET_SEARCH_LOW_DB <= plan.resolved_noise_threshold <= TARGET_SEARCH_HIGH_DB
        assert plan.resulting_length_sec <= plan.input_duration_sec + 0.001, \
            f"Result exceeds input duration: {plan.resulting_length_sec:.2f}s > {plan.input_duration_sec:.2f}s"

        if plan.should_copy_input:
            assert abs(plan.resulting_length_sec - plan.input_duration_sec) < 0.001, \
                f"Copy mode: resulting length should equal input duration"
            assert len(plan.segments_to_keep) == 1, "Copy mode should have single segment [0, duration]"
            assert plan.segments_to_keep[0][0] == 0.0, "Copy mode segment should start at 0"


class TestNonTargetMode:
    """Test non-target mode (aggressive silence removal)."""
    
    def test_non_target_on_vertical_video(self, sample_vertical):
        """Test non-target mode on vertical video."""
        plan = build_trim_plan(
            input_file=sample_vertical,
            target_length=None,
            noise_threshold=NON_TARGET_NOISE_THRESHOLD_DB,
            min_duration=NON_TARGET_MIN_DURATION_SEC,
            pad_sec=NON_TARGET_PAD_SEC,
        )
        
        validate_trim_plan(plan, sample_vertical)
        assert plan.mode == "non_target"
    
    def test_non_target_on_video_with_silence(self, sample_with_silence):
        """Test non-target mode on video with known silence sections."""
        plan = build_trim_plan(
            input_file=sample_with_silence,
            target_length=None,
            noise_threshold=NON_TARGET_NOISE_THRESHOLD_DB,
            min_duration=NON_TARGET_MIN_DURATION_SEC,
            pad_sec=NON_TARGET_PAD_SEC,
        )
        
        validate_trim_plan(plan, sample_with_silence)
        # Note: 1-second silence sections may not be detected if min_duration >= 1.0
        # This test validates the plan is valid, not that it trims significantly
    
    def test_non_target_on_short_video(self, sample_short):
        """Test non-target mode on short video."""
        plan = build_trim_plan(
            input_file=sample_short,
            target_length=None,
            noise_threshold=NON_TARGET_NOISE_THRESHOLD_DB,
            min_duration=NON_TARGET_MIN_DURATION_SEC,
            pad_sec=NON_TARGET_PAD_SEC,
        )
        
        validate_trim_plan(plan, sample_short)


class TestTargetMode:
    """Test target mode with various video lengths."""

    def test_target_mode_copy_through_uses_canonical_metadata(self, sample_short):
        """Target copy-through still reports the fixed target-mode search policy."""
        plan = build_trim_plan(
            input_file=sample_short,
            target_length=5.0,
            noise_threshold=-10.0,
            min_duration=9.0,
            pad_sec=9.0,
        )

        validate_trim_plan(plan, sample_short)
        assert plan.mode == "target"
        assert plan.should_copy_input is True
        assert plan.resolved_noise_threshold == TARGET_SEARCH_LOW_DB
        assert plan.resolved_min_duration == TARGET_SEARCH_MIN_SILENCE_LEN_SEC
        assert plan.resolved_pad_sec == TARGET_SEARCH_BASE_PADDING_SEC

    def test_target_mode_reachable_target_stays_under_target(self, sample_with_silence):
        """Reachable target cases should stay at or under target without truncation."""
        target_length = 3.5
        plan = build_trim_plan(
            input_file=sample_with_silence,
            target_length=target_length,
            noise_threshold=-55.0,
            min_duration=0.01,
            pad_sec=0.0,
        )

        validate_trim_plan(plan, sample_with_silence)
        assert plan.mode == "target"
        assert plan.should_copy_input is False
        assert plan.resulting_length_sec <= target_length + 0.001
        assert plan.resolved_pad_sec >= TARGET_SEARCH_BASE_PADDING_SEC

    def test_target_mode_unreachable_target_returns_best_effort(self, sample_vertical):
        """Unreachable targets should fall back to -35 dB / 0.060s without truncation."""
        target_length = 1.0
        plan = build_trim_plan(
            input_file=sample_vertical,
            target_length=target_length,
            noise_threshold=-55.0,
            min_duration=0.01,
            pad_sec=0.0,
        )

        validate_trim_plan(plan, sample_vertical)
        assert plan.mode == "target"
        assert plan.should_copy_input is False
        assert plan.resolved_noise_threshold == TARGET_SEARCH_HIGH_DB
        assert plan.resolved_pad_sec == TARGET_SEARCH_BASE_PADDING_SEC
        assert plan.resulting_length_sec > target_length

    def test_target_mode_ignores_custom_overrides(self, sample_with_silence):
        """Target mode should ignore caller overrides and resolve to the fixed internal policy."""
        canonical_plan = build_trim_plan(
            input_file=sample_with_silence,
            target_length=3.5,
            noise_threshold=TARGET_SEARCH_LOW_DB,
            min_duration=TARGET_SEARCH_MIN_SILENCE_LEN_SEC,
            pad_sec=TARGET_SEARCH_BASE_PADDING_SEC,
        )
        overridden_plan = build_trim_plan(
            input_file=sample_with_silence,
            target_length=3.5,
            noise_threshold=-10.0,
            min_duration=9.0,
            pad_sec=4.0,
        )

        assert overridden_plan == canonical_plan


class TestSnippetMode:
    """Test snippet mode for transcription."""
    
    def test_snippet_mode(self, sample_vertical):
        """Test snippet mode generates short preview."""
        plan = build_trim_plan(
            input_file=sample_vertical,
            target_length=SNIPPET_MAX_DURATION_SEC,
            noise_threshold=NON_TARGET_NOISE_THRESHOLD_DB,
            min_duration=NON_TARGET_MIN_DURATION_SEC,
            pad_sec=NON_TARGET_PAD_SEC,
        )
        
        validate_trim_plan(plan, sample_vertical)
        # Result should be limited to snippet max duration
        assert plan.resulting_length_sec <= SNIPPET_MAX_DURATION_SEC + 0.1


class TestBlackBoxApi:
    """Test the public API surface."""
    
    def test_imports(self):
        """Test that all public symbols can be imported."""
        from sr_trim_plan import build_trim_plan, TrimPlan
        assert callable(build_trim_plan)
        assert isinstance(TrimPlan, type)
    
    def test_build_trim_plan_signature(self, sample_vertical):
        """Test build_trim_plan() accepts required parameters."""
        plan = build_trim_plan(
            input_file=sample_vertical,
            target_length=None,
            noise_threshold=-30.0,
            min_duration=0.5,
            pad_sec=0.1,
        )
        
        assert isinstance(plan, TrimPlan)
        assert plan.input_duration_sec > 0
        assert len(plan.segments_to_keep) > 0
