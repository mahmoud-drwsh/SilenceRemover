"""Tests for pipeline display module."""

import pytest
from src.app.pipeline_display import PipelineProgress


class TestPipelineProgress:
    """Test cases for PipelineProgress class."""

    def test_initialization_with_rich(self):
        """Test that PipelineProgress initializes correctly with Rich."""
        progress = PipelineProgress(use_rich=True)
        assert progress._rich_available is True
        assert progress._progress is not None

    def test_initialization_without_rich(self):
        """Test that PipelineProgress falls back when Rich disabled."""
        progress = PipelineProgress(use_rich=False)
        assert progress._rich_available is False
        assert progress._fallback is not None

    def test_context_manager(self):
        """Test that PipelineProgress works as context manager."""
        with PipelineProgress(use_rich=False) as progress:
            assert progress is not None
            progress.start_pipeline(total_phases=8, total_videos=10)

    def test_start_phase_with_fallback(self):
        """Test start_phase with fallback display."""
        progress = PipelineProgress(use_rich=False)
        progress.start_pipeline(total_phases=8, total_videos=10)
        # Should not raise
        progress.start_phase(5, "Overlay Generation", "test_video.mp4")

    def test_update_status_with_fallback(self):
        """Test update_status with fallback display."""
        progress = PipelineProgress(use_rich=False)
        progress.start_pipeline(total_phases=8, total_videos=10)
        progress.start_phase(5, "Overlay Generation", "test_video.mp4")
        # Should not raise
        progress.update_status("done")
        progress.update_status("skip", "already processed")
        progress.update_status("error", "file not found")

    def test_filename_truncation(self):
        """Test that long filenames are truncated."""
        progress = PipelineProgress(use_rich=False)
        progress.start_pipeline(total_phases=8, total_videos=10)
        long_name = "a" * 100 + ".mp4"
        # Should not raise and should truncate
        progress.start_phase(5, "Overlay Generation", long_name)

    def test_print_summary_with_fallback(self):
        """Test print_summary with fallback display."""
        progress = PipelineProgress(use_rich=False)
        # Should not raise
        progress.print_summary(success=5, skipped=2, failed=1)

    def test_invalid_status(self):
        """Test that invalid status defaults gracefully."""
        progress = PipelineProgress(use_rich=False)
        progress.start_pipeline(total_phases=8, total_videos=10)
        progress.start_phase(5, "Overlay Generation", "test.mp4")
        # Invalid status should use default (? symbol, white style)
        progress.update_status("invalid_status")  # type: ignore
