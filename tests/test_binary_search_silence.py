"""Compatibility tests for legacy binary-search helpers; natural mode uses a pause budget."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

import sr_trim_plan.api as trim_plan_api
from sr_trim_plan.api import binary_search_padding, binary_search_threshold
from src.core.constants import (
    NATURAL_TARGET_NOISE_THRESHOLD_DB,
    NATURAL_TARGET_MIN_SILENCE_SEC,
    TARGET_SEARCH_BASE_PADDING_SEC,
    TARGET_SEARCH_HIGH_DB,
    TARGET_SEARCH_LOW_DB,
    TARGET_SEARCH_MIN_SILENCE_LEN_SEC,
    TARGET_SEARCH_PADDING_STEP_SEC,
    TARGET_SEARCH_STEP_DB,
    resolve_trim_defaults,
)


class TestTargetSearchConstants:
    """Verify the live target-mode search constants and defaults."""

    def test_target_search_constant_values(self):
        assert TARGET_SEARCH_LOW_DB == -60.0
        assert TARGET_SEARCH_HIGH_DB == -35.0
        assert TARGET_SEARCH_STEP_DB == 0.1
        assert TARGET_SEARCH_MIN_SILENCE_LEN_SEC == 0.100
        assert TARGET_SEARCH_BASE_PADDING_SEC == 0.060
        assert TARGET_SEARCH_PADDING_STEP_SEC == 0.01

        count = int(round((TARGET_SEARCH_HIGH_DB - TARGET_SEARCH_LOW_DB) / TARGET_SEARCH_STEP_DB)) + 1
        assert count == 251

    def test_target_defaults_ignore_overrides(self):
        defaults = resolve_trim_defaults(
            target_length=90.0,
            noise_threshold=-12.0,
            min_duration=9.0,
            pad_sec=4.0,
        )

        assert defaults.noise_threshold == NATURAL_TARGET_NOISE_THRESHOLD_DB
        assert defaults.min_duration == NATURAL_TARGET_MIN_SILENCE_SEC
        assert defaults.pad_sec == 0.3


class TestCacheFilenameEncoding:
    """Verify single-file cache addressing for silence analysis."""

    def test_cache_path_is_single_file_per_video(self):
        from packages.sr_silence_detection._cache import _get_cache_path

        temp_dir = Path("/tmp/temp")
        path = _get_cache_path(temp_dir, "Video")

        expected = temp_dir / "silence" / "Video.json"
        assert path == expected

    def test_primary_cache_key_is_stable(self):
        from packages.sr_silence_detection._cache import _get_primary_cache_key

        assert _get_primary_cache_key(TARGET_SEARCH_MIN_SILENCE_LEN_SEC, -60.0) == "d:0.100|t:-60.000"
        assert _get_primary_cache_key(0.375, -59.75) == "d:0.375|t:-59.750"
        assert _get_primary_cache_key(0.5, 0.0) == "d:0.500|t:0.000"


class TestThresholdBinarySearch:
    """Verify threshold binary search behavior without FFmpeg."""

    def test_chooses_earliest_valid_threshold(self):
        threshold_db, reached_target = binary_search_threshold(
            target_length=10.0,
            estimate_length=lambda threshold_db: 12.0 if threshold_db < -52.3 else 9.0,
        )

        assert reached_target is True
        assert threshold_db == pytest.approx(-52.3)

    def test_falls_back_to_high_threshold_when_unreachable(self):
        threshold_db, reached_target = binary_search_threshold(
            target_length=10.0,
            estimate_length=lambda _threshold_db: 12.0,
        )

        assert reached_target is False
        assert threshold_db == TARGET_SEARCH_HIGH_DB

    def test_invalid_probe_is_treated_as_overshoot(self):
        def estimate_length(threshold_db: float) -> float | None:
            if threshold_db <= -49.0:
                return None
            if threshold_db < -47.0:
                return 12.0
            return 9.0

        threshold_db, reached_target = binary_search_threshold(
            target_length=10.0,
            estimate_length=estimate_length,
        )

        assert reached_target is True
        assert threshold_db == pytest.approx(-47.0)



class TestPaddingBinarySearch:
    """Verify padding binary search behavior without FFmpeg re-runs."""

    def test_chooses_largest_valid_padding_step(self):
        pad_sec = binary_search_padding(
            target_length=10.0,
            duration_sec=5.0,
            estimate_length=lambda pad_sec: 9.60 + pad_sec,
        )

        assert pad_sec == pytest.approx(0.400)

    def test_returns_base_padding_when_no_expansion_is_possible(self):
        pad_sec = binary_search_padding(
            target_length=9.769,
            duration_sec=5.0,
            estimate_length=lambda pad_sec: 9.70 + pad_sec,
        )

        assert pad_sec == TARGET_SEARCH_BASE_PADDING_SEC

    def test_invalid_padding_probe_falls_back_safely(self):
        def estimate_length(pad_sec: float) -> float | None:
            if pad_sec >= 0.37:
                return None
            return 9.50 + pad_sec

        pad_sec = binary_search_padding(
            target_length=10.0,
            duration_sec=5.0,
            estimate_length=estimate_length,
        )

        assert pad_sec == pytest.approx(0.360)

    def test_invalid_base_padding_returns_default(self):
        pad_sec = binary_search_padding(
            target_length=10.0,
            duration_sec=5.0,
            estimate_length=lambda _pad_sec: None,
        )

        assert pad_sec == TARGET_SEARCH_BASE_PADDING_SEC
