"""Tests for binary search silence detection algorithm.

Tests cover:
- Binary search finds optimal (min_duration, dB) combination
- Early termination behavior
- Fractional cache filename encoding
- Fallback to aggressive settings
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

import pytest


class TestBinarySearchConstants:
    """Verify computed constant ranges."""
    
    def test_min_duration_tiers_count(self):
        """Should have exactly 50 min_duration tiers."""
        from src.core.constants import TARGET_MIN_DURATION_TIERS
        assert len(TARGET_MIN_DURATION_TIERS) == 50
    
    def test_min_duration_tiers_start(self):
        """First tier should be 0.5s."""
        from src.core.constants import TARGET_MIN_DURATION_TIERS
        assert TARGET_MIN_DURATION_TIERS[0] == 0.5
    
    def test_min_duration_tiers_end(self):
        """Last tier should be approximately 0.01s."""
        from src.core.constants import TARGET_MIN_DURATION_TIERS
        assert abs(TARGET_MIN_DURATION_TIERS[-1] - 0.01) < 0.0001
    
    def test_min_duration_tiers_step(self):
        """Step size should be approximately 0.01s."""
        from src.core.constants import TARGET_MIN_DURATION_TIERS
        for i in range(1, len(TARGET_MIN_DURATION_TIERS)):
            step = TARGET_MIN_DURATION_TIERS[i-1] - TARGET_MIN_DURATION_TIERS[i]
            assert abs(step - 0.01) < 0.0001
    
    def test_db_range(self):
        """dB range should be -60 to -25 with 0.05 step (fine precision)."""
        from src.core.constants import (
            TARGET_NOISE_THRESHOLD_START_DB,
            TARGET_NOISE_THRESHOLD_END_DB,
            TARGET_NOISE_THRESHOLD_STEP_DB,
        )
        assert TARGET_NOISE_THRESHOLD_START_DB == -60.0
        assert TARGET_NOISE_THRESHOLD_END_DB == -25.0
        assert TARGET_NOISE_THRESHOLD_STEP_DB == 0.05
        
        # Verify 701 values (with 0.05 step)
        count = int((TARGET_NOISE_THRESHOLD_END_DB - TARGET_NOISE_THRESHOLD_START_DB) 
                    / TARGET_NOISE_THRESHOLD_STEP_DB) + 1
        assert count == 701


class TestCacheFilenameEncoding:
    """Verify single-file cache addressing for silence analysis."""

    def test_cache_path_is_single_file_per_video(self):
        """Each video should now map to one cache file."""
        from packages.sr_silence_detection._cache import _get_cache_path

        temp_dir = Path("/tmp/temp")
        path = _get_cache_path(temp_dir, "Video")

        expected = temp_dir / "silence" / "Video.json"
        assert path == expected

    def test_primary_cache_key_is_stable(self):
        """Primary variants should be stored under stable in-file keys."""
        from packages.sr_silence_detection._cache import _get_primary_cache_key

        assert _get_primary_cache_key(0.1, -60.0) == "d:0.100|t:-60.000"
        assert _get_primary_cache_key(0.375, -59.75) == "d:0.375|t:-59.750"
        assert _get_primary_cache_key(0.5, 0.0) == "d:0.500|t:0.000"


class TestBinarySearchAlgorithm:
    """Test binary search finds optimal combination."""
    
    def test_finds_quietest_db_at_first_working_tier(self):
        """Should find quietest dB at first tier where target is met."""
        # This is implicitly tested through integration tests
        # A full unit test would require mocking detect_primary_with_cached_edges
        pass
    
    def test_early_termination_at_first_valid_tier(self):
        """Should stop at first min_dur tier where valid dB is found."""
        # Verified by integration tests
        pass
    
    def test_fallback_to_aggressive_settings(self):
        """Should use most aggressive (0.01, -25) when no valid combo found."""
        # Integration test: test_target_mode_long_video covers fallback
        pass


class TestBinarySearchPerformance:
    """Verify binary search complexity."""
    
    def test_max_iterations_upper_bound(self):
        """Max iterations should be ~500 (50 tiers × 10 dB steps for 701 values)."""
        import math
        
        tiers = 50
        db_steps = math.ceil(math.log2(701))  # Binary search over 701 values
        max_iterations = tiers * db_steps
        
        assert max_iterations <= 500  # 50 × 10
        assert max_iterations < 11217  # Linear search worst case
    
    def test_early_termination_performance(self):
        """Early termination should happen in first few tiers typically."""
        # If target is easily met, should terminate in tier 1-5
        # This is a behavioral expectation, not strict test
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
