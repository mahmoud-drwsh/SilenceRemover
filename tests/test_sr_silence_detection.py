"""Integration tests for sr_silence_detection package.

Tests run against generated fixture videos. Generate fixtures with:
    python tests/generate_fixtures.py
"""

import sys
from pathlib import Path

import pytest

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

from sr_silence_detection import detect_silence, detect_silence_with_edges
from src.core.constants import (
    EDGE_RESCAN_MIN_DURATION_SEC,
    EDGE_RESCAN_THRESHOLD_DB,
    EDGE_SILENCE_KEEP_SEC,
    NON_TARGET_MIN_DURATION_SEC,
    NON_TARGET_NOISE_THRESHOLD_DB,
    TARGET_MIN_DURATION_SEC,
    TARGET_NOISE_THRESHOLD_DB,
)


class TestSimpleDetection:
    """Test detect_silence() - single-pass detection."""
    
    def test_detects_silence_in_normal_video(self, sample_vertical):
        """Test basic silence detection on normal video."""
        starts, ends = detect_silence(
            input_file=sample_vertical,
            noise_threshold=NON_TARGET_NOISE_THRESHOLD_DB,
            min_duration=NON_TARGET_MIN_DURATION_SEC,
        )
        
        # Sanity checks
        assert len(starts) == len(ends)
        for s, e in zip(starts, ends):
            assert s < e
            assert s >= 0
    
    def test_detects_silence_sections_in_video(self, sample_with_silence):
        """Test detection of known silence sections."""
        starts, ends = detect_silence(
            input_file=sample_with_silence,
            noise_threshold=NON_TARGET_NOISE_THRESHOLD_DB,
            min_duration=0.1,  # Lower threshold to catch 1-second silences
        )
        
        # Should find at least 2 silence sections (at 1-2s and 3-4s)
        assert len(starts) >= 2
        assert len(starts) == len(ends)
        
        # Verify intervals are reasonable
        total_silence = sum(e - s for s, e in zip(starts, ends))
        assert total_silence > 0
    
    def test_handles_varying_audio(self, sample_varying_audio):
        """Test detection on video with varying audio levels."""
        starts, ends = detect_silence(
            input_file=sample_varying_audio,
            noise_threshold=NON_TARGET_NOISE_THRESHOLD_DB,
            min_duration=NON_TARGET_MIN_DURATION_SEC,
        )
        
        assert len(starts) == len(ends)
        for s, e in zip(starts, ends):
            assert s < e
            assert s >= 0
    
    def test_handles_short_video(self, sample_short):
        """Test detection on short 2-second video."""
        starts, ends = detect_silence(
            input_file=sample_short,
            noise_threshold=NON_TARGET_NOISE_THRESHOLD_DB,
            min_duration=NON_TARGET_MIN_DURATION_SEC,
        )
        
        assert len(starts) == len(ends)


class TestEdgeAwareDetection:
    """Test detect_silence_with_edges() - dual-pass with edge policy."""
    
    def test_edge_aware_on_normal_video(self, sample_vertical):
        """Test edge-aware detection on normal video."""
        starts, ends = detect_silence_with_edges(
            input_file=sample_vertical,
            primary_noise_threshold=TARGET_NOISE_THRESHOLD_DB,
            primary_min_duration=TARGET_MIN_DURATION_SEC,
            edge_noise_threshold=EDGE_RESCAN_THRESHOLD_DB,
            edge_min_duration=EDGE_RESCAN_MIN_DURATION_SEC,
            edge_keep_seconds=EDGE_SILENCE_KEEP_SEC,
        )
        
        # Sanity checks
        assert len(starts) == len(ends)
        for s, e in zip(starts, ends):
            assert s < e
            assert s >= 0
    
    def test_edge_aware_preserves_edges(self, sample_with_silence):
        """Test that edge-aware mode properly handles file edges."""
        starts, ends = detect_silence_with_edges(
            input_file=sample_with_silence,
            primary_noise_threshold=TARGET_NOISE_THRESHOLD_DB,
            primary_min_duration=0.1,
            edge_noise_threshold=EDGE_RESCAN_THRESHOLD_DB,
            edge_min_duration=EDGE_RESCAN_MIN_DURATION_SEC,
            edge_keep_seconds=EDGE_SILENCE_KEEP_SEC,
        )
        
        assert len(starts) == len(ends)
        
        # Verify intervals are sorted and non-overlapping
        for i in range(len(starts) - 1):
            assert ends[i] <= starts[i + 1]
    
    def test_edge_aware_on_short_video(self, sample_short):
        """Test edge-aware detection on short video."""
        starts, ends = detect_silence_with_edges(
            input_file=sample_short,
            primary_noise_threshold=TARGET_NOISE_THRESHOLD_DB,
            primary_min_duration=TARGET_MIN_DURATION_SEC,
            edge_noise_threshold=EDGE_RESCAN_THRESHOLD_DB,
            edge_min_duration=EDGE_RESCAN_MIN_DURATION_SEC,
            edge_keep_seconds=EDGE_SILENCE_KEEP_SEC,
        )
        
        assert len(starts) == len(ends)


class TestBlackBoxApi:
    """Test the public API surface."""
    
    def test_imports(self):
        """Test that all public functions can be imported."""
        from sr_silence_detection import detect_silence, detect_silence_with_edges
        assert callable(detect_silence)
        assert callable(detect_silence_with_edges)
    
    def test_detect_silence_signature(self, sample_vertical):
        """Test detect_silence() accepts required parameters."""
        result = detect_silence(
            input_file=sample_vertical,
            noise_threshold=-30.0,
            min_duration=0.5,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        starts, ends = result
        assert isinstance(starts, list)
        assert isinstance(ends, list)
    
    def test_detect_silence_with_edges_signature(self, sample_vertical):
        """Test detect_silence_with_edges() accepts required parameters."""
        result = detect_silence_with_edges(
            input_file=sample_vertical,
            primary_noise_threshold=-30.0,
            primary_min_duration=0.5,
            edge_noise_threshold=-40.0,
            edge_min_duration=0.2,
            edge_keep_seconds=0.3,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
