"""Pure unit tests for the live target-mode binary-search helpers."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

import sr_trim_plan.api as trim_plan_api
from sr_trim_plan.api import binary_search_padding, binary_search_threshold
from src.core.constants import (
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
        assert TARGET_SEARCH_MIN_SILENCE_LEN_SEC == 0.085
        assert TARGET_SEARCH_BASE_PADDING_SEC == 0.085
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

        assert defaults.noise_threshold == TARGET_SEARCH_LOW_DB
        assert defaults.min_duration == TARGET_SEARCH_MIN_SILENCE_LEN_SEC
        assert defaults.pad_sec == TARGET_SEARCH_BASE_PADDING_SEC


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

        assert _get_primary_cache_key(TARGET_SEARCH_MIN_SILENCE_LEN_SEC, -60.0) == "d:0.085|t:-60.000"
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

    def test_build_trim_plan_uses_best_effort_fallback_when_all_threshold_probes_fail(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        input_file = tmp_path / "input.mp4"
        input_file.write_bytes(b"video")

        monkeypatch.setattr(trim_plan_api, "probe_duration", lambda _path: 12.0)
        monkeypatch.setattr(trim_plan_api, "detect_edge_only_cached", lambda *args, **kwargs: ([], []))

        def _raise_invalid_probe(*args, **kwargs):
            raise RuntimeError("probe failed")

        monkeypatch.setattr(trim_plan_api, "detect_primary_with_cached_edges", _raise_invalid_probe)

        plan = trim_plan_api.build_trim_plan(
            input_file=input_file,
            target_length=5.0,
            noise_threshold=-55.0,
            min_duration=0.01,
            pad_sec=0.0,
            temp_dir=tmp_path,
        )

        assert plan.mode == "target"
        assert plan.should_copy_input is False
        assert plan.resolved_noise_threshold == TARGET_SEARCH_HIGH_DB
        assert plan.resolved_min_duration == TARGET_SEARCH_MIN_SILENCE_LEN_SEC
        assert plan.resolved_pad_sec == TARGET_SEARCH_BASE_PADDING_SEC
        assert plan.segments_to_keep == [(0.0, 12.0)]
        assert plan.resulting_length_sec == 12.0


class TestPaddingBinarySearch:
    """Verify padding binary search behavior without FFmpeg re-runs."""

    def test_chooses_largest_valid_padding_step(self):
        pad_sec = binary_search_padding(
            target_length=10.0,
            duration_sec=5.0,
            estimate_length=lambda pad_sec: 9.60 + pad_sec,
        )

        assert pad_sec == pytest.approx(0.395)

    def test_returns_base_padding_when_no_expansion_is_possible(self):
        pad_sec = binary_search_padding(
            target_length=9.79,
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

        assert pad_sec == pytest.approx(0.365)

    def test_invalid_base_padding_returns_default(self):
        pad_sec = binary_search_padding(
            target_length=10.0,
            duration_sec=5.0,
            estimate_length=lambda _pad_sec: None,
        )

        assert pad_sec == TARGET_SEARCH_BASE_PADDING_SEC
