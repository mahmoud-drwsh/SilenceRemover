"""Unit tests for sr_filter_graph package.

Pure function tests - no FFmpeg, no file I/O, just deterministic string building.
"""

import sys
from pathlib import Path

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

import pytest

from sr_filter_graph import (
    build_audio_concat_filter_graph,
    build_filter_graph_script,
    build_video_audio_concat_filter_graph,
    build_video_lavfi_audio_concat_filter_graph,
    _escape_ffmpeg_single_quoted_path,
    _segment_audio_duration_sec,
)


class TestCoreUtilities:
    """Test _core.py utility functions."""
    
    def test_segment_audio_duration_sec_normal(self):
        """Test duration calculation with normal values."""
        assert _segment_audio_duration_sec(0.0, 5.0) == 5.0
        assert _segment_audio_duration_sec(10.0, 15.5) == 5.5
    
    def test_segment_audio_duration_sec_epsilon_guard(self):
        """Test that very small durations are clamped to epsilon."""
        # Zero-length segments should return epsilon
        assert _segment_audio_duration_sec(5.0, 5.0) == 1e-6
        # Negative durations should also return epsilon
        assert _segment_audio_duration_sec(5.0, 4.0) == 1e-6
        # Very small positive durations should return epsilon
        assert _segment_audio_duration_sec(0.0, 0.0000001) == 1e-6


class TestEscaping:
    """Test _escaping.py path escaping."""
    
    def test_escape_single_quote(self):
        """Test escaping single quotes in paths."""
        assert _escape_ffmpeg_single_quoted_path("file'name") == "file\\'name"
    
    def test_escape_backslash(self):
        """Test escaping backslashes in paths."""
        assert _escape_ffmpeg_single_quoted_path("path\\to\\file") == "path\\\\to\\\\file"
    
    def test_escape_both(self):
        """Test escaping both single quotes and backslashes."""
        input_str = "path\\to\\file'name"
        expected = "path\\\\to\\\\file\\'name"
        assert _escape_ffmpeg_single_quoted_path(input_str) == expected
    
    def test_no_special_chars(self):
        """Test that normal paths are unchanged."""
        normal = "/path/to/normal/file.mp4"
        assert _escape_ffmpeg_single_quoted_path(normal) == normal


class TestFilterGraphScript:
    """Test build_filter_graph_script core builder."""
    
    def test_audio_only_concat(self):
        """Test audio-only concat script."""
        result = build_filter_graph_script(
            segment_count=2,
            filter_chains="[0:a]atrim=start=0:end=5,asetpts=PTS-STARTPTS[a0];[0:a]atrim=start=10:end=15,asetpts=PTS-STARTPTS[a1];",
            concat_inputs="[a0][a1]",
            include_video=False,
        )
        assert "concat=n=2:v=0:a=1[outa]" in result
        assert "[outv]" not in result
    
    def test_video_audio_concat(self):
        """Test video+audio concat script."""
        result = build_filter_graph_script(
            segment_count=1,
            filter_chains="[0:v]trim=start=0:end=5,setpts=PTS-STARTPTS[v0];[0:a]atrim=start=0:end=5,asetpts=PTS-STARTPTS[a0];",
            concat_inputs="[v0][a0]",
            include_video=True,
        )
        assert "concat=n=1:v=1:a=1[outv][outa]" in result


class TestAudioConcat:
    """Test build_audio_concat_filter_graph."""
    
    def test_single_segment(self):
        """Test audio concat with single segment."""
        result = build_audio_concat_filter_graph([(0.0, 5.0)])
        assert "[0:a]atrim=start=0.0:end=5.0,asetpts=PTS-STARTPTS[a0]" in result
        assert "[a0]concat=n=1:v=0:a=1[outa]" in result
    
    def test_multiple_segments(self):
        """Test audio concat with multiple segments."""
        segments = [(0.0, 2.0), (5.0, 7.0), (10.0, 15.0)]
        result = build_audio_concat_filter_graph(segments)
        assert "atrim=start=0.0:end=2.0" in result
        assert "atrim=start=5.0:end=7.0" in result
        assert "atrim=start=10.0:end=15.0" in result
        assert "[a0][a1][a2]concat=n=3:v=0:a=1[outa]" in result
    
    def test_empty_segments(self):
        """Test audio concat with no segments."""
        result = build_audio_concat_filter_graph([])
        assert "concat=n=0:v=0:a=1[outa]" in result


class TestVideoAudioConcat:
    """Test build_video_audio_concat_filter_graph."""
    
    def test_single_segment(self):
        """Test video+audio concat with single segment."""
        result = build_video_audio_concat_filter_graph([(0.0, 3.0)])
        assert "[0:v]trim=start=0.0:end=3.0,setpts=PTS-STARTPTS[v0]" in result
        assert "[0:a]atrim=start=0.0:end=3.0,asetpts=PTS-STARTPTS[a0]" in result
        assert "[v0][a0]concat=n=1:v=1:a=1[outv][outa]" in result
    
    def test_multiple_segments(self):
        """Test video+audio concat with multiple segments."""
        segments = [(0.0, 1.0), (2.0, 3.0)]
        result = build_video_audio_concat_filter_graph(segments)
        assert "trim=start=0.0:end=1.0" in result
        assert "trim=start=2.0:end=3.0" in result
        assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[outv][outa]" in result


class TestVideoLavfiConcat:
    """Test build_video_lavfi_audio_concat_filter_graph."""
    
    def test_single_segment(self):
        """Test video+lavfi concat with single segment."""
        result = build_video_lavfi_audio_concat_filter_graph([(0.0, 5.0)])
        assert "[0:v]trim=start=0.0:end=5.0,setpts=PTS-STARTPTS[v0]" in result
        assert "[1:a]atrim=start=0:end=5.0" in result  # Lavfi audio with matching duration
        assert "[v0][a0]concat=n=1:v=1:a=1[outv][outa]" in result
    
    def test_multiple_segments(self):
        """Test video+lavfi concat calculates durations correctly."""
        segments = [(0.0, 2.5), (5.0, 10.0)]  # durations: 2.5, 5.0
        result = build_video_lavfi_audio_concat_filter_graph(segments)
        assert "atrim=start=0:end=2.5" in result
        assert "atrim=start=0:end=5.0" in result
