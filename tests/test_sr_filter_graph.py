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
    build_minimal_encode_overlay_filter_complex,
    build_video_audio_concat_filter_graph,
    build_video_audio_concat_filter_graph_with_title_overlay,
    build_video_lavfi_audio_concat_filter_graph,
    build_video_lavfi_audio_concat_filter_graph_with_title_overlay,
    _escape_ffmpeg_single_quoted_path,
    _has_logo_overlay,
    _lavfi_input_index,
    _overlay_suffix_after_concat,
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
    
    def test_lavfi_input_index_no_overlays(self):
        """Test lavfi input index with no overlays."""
        assert _lavfi_input_index(has_title=False, has_logo=False) == 1
    
    def test_lavfi_input_index_title_only(self):
        """Test lavfi input index with title only."""
        assert _lavfi_input_index(has_title=True, has_logo=False) == 2
    
    def test_lavfi_input_index_logo_only(self):
        """Test lavfi input index with logo only."""
        assert _lavfi_input_index(has_title=False, has_logo=True) == 2
    
    def test_lavfi_input_index_both_overlays(self):
        """Test lavfi input index with both title and logo."""
        assert _lavfi_input_index(has_title=True, has_logo=True) == 3


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


class TestLogoOverlay:
    """Test _overlay.py logo overlay detection."""
    
    def test_has_logo_overlay_true(self):
        """Test that True values are detected."""
        assert _has_logo_overlay(True) is True
        assert _has_logo_overlay(1) is True
        assert _has_logo_overlay("logo") is True  # Non-empty string is truthy
    
    def test_has_logo_overlay_false(self):
        """Test that False values are detected."""
        assert _has_logo_overlay(False) is False
        assert _has_logo_overlay(0) is False
        assert _has_logo_overlay(None) is False
        assert _has_logo_overlay("") is False


class TestOverlaySuffix:
    """Test _overlay_suffix_after_concat building."""
    
    def test_empty_when_both_disabled(self):
        """Test that empty string is returned when both overlays disabled."""
        result = _overlay_suffix_after_concat(
            title_overlay_y=None,
            logo_enabled=False,
        )
        assert result == ""
    
    def test_title_only_overlay(self):
        """Test building title-only overlay suffix."""
        result = _overlay_suffix_after_concat(
            title_overlay_y=100,
            logo_enabled=False,
        )
        assert "[1:v]format=rgba[ov_title]" in result
        assert "overlay=0:100" in result
        assert "format=nv12[outv]" in result
        assert "colorchannelmixer" not in result  # No logo
    
    def test_logo_only_overlay(self):
        """Test building logo-only overlay suffix."""
        result = _overlay_suffix_after_concat(
            title_overlay_y=None,
            logo_enabled=True,
            logo_margin_px=10,
            logo_alpha=0.8,
        )
        assert "[1:v]format=rgba,colorchannelmixer=aa=0.8" in result
        assert "overlay=W-w-10:10" in result
        assert "format=nv12[outv]" in result
        assert "[ov_title]" not in result  # No title
    
    def test_both_overlays(self):
        """Test building both title and logo overlay suffix."""
        result = _overlay_suffix_after_concat(
            title_overlay_y=150,
            logo_enabled=True,
            logo_margin_px=20,
            logo_alpha=0.5,
        )
        # Logo should be at stream index 2 when title is present
        assert "[2:v]format=rgba,colorchannelmixer=aa=0.5" in result
        assert "overlay=W-w-20:20" in result  # Logo positioned with margin
        assert "[1:v]format=rgba[ov_title]" in result  # Title at index 1
        assert "overlay=0:150" in result  # Title at y=150
        assert "format=nv12[outv]" in result
    
    def test_default_alpha_and_margin(self):
        """Test default values for alpha and margin."""
        result = _overlay_suffix_after_concat(
            title_overlay_y=None,
            logo_enabled=True,
        )
        assert "aa=1.0" in result  # Default alpha
        assert "overlay=W-w-0:0" in result  # Default margin


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


class TestVideoAudioConcatWithOverlay:
    """Test build_video_audio_concat_filter_graph_with_title_overlay."""
    
    def test_title_only(self):
        """Test concat with title overlay only."""
        segments = [(0.0, 5.0)]
        result = build_video_audio_concat_filter_graph_with_title_overlay(
            segments,
            overlay_y=100,
            logo_enabled=False,
        )
        assert "trim=start=0.0:end=5.0" in result
        assert "[1:v]format=rgba[ov_title]" in result
        assert "overlay=0:100" in result
        assert "format=nv12[outv]" in result
    
    def test_logo_only(self):
        """Test concat with logo overlay only."""
        segments = [(0.0, 3.0)]
        result = build_video_audio_concat_filter_graph_with_title_overlay(
            segments,
            overlay_y=None,
            logo_enabled=True,
            logo_margin_px=10,
            logo_alpha=0.75,
        )
        # Logo at index 1 when no title
        assert "[1:v]format=rgba,colorchannelmixer=aa=0.75" in result
        assert "overlay=W-w-10:10" in result
    
    def test_both_overlays(self):
        """Test concat with both title and logo overlays."""
        segments = [(1.0, 4.0), (6.0, 9.0)]
        result = build_video_audio_concat_filter_graph_with_title_overlay(
            segments,
            overlay_y=200,
            logo_enabled=True,
            logo_margin_px=15,
            logo_alpha=0.9,
        )
        # Should have two segments
        assert "concat=n=2:v=1:a=1[outv][outa]" in result
        # Logo at index 2, title at index 1
        assert "[2:v]format=rgba,colorchannelmixer=aa=0.9" in result
        assert "[1:v]format=rgba[ov_title]" in result
        assert "overlay=0:200" in result  # Title position
    
    def test_error_when_both_disabled(self):
        """Test that error is raised when both overlays disabled."""
        with pytest.raises(ValueError, match="cannot both be disabled"):
            build_video_audio_concat_filter_graph_with_title_overlay(
                [(0.0, 1.0)],
                overlay_y=None,
                logo_enabled=False,
            )


class TestMinimalEncodeOverlay:
    """Test build_minimal_encode_overlay_filter_complex."""
    
    def test_title_only(self):
        """Test minimal overlay with title only."""
        result = build_minimal_encode_overlay_filter_complex(
            title_overlay_y=50,
            logo_enabled=False,
        )
        assert "[0:v]" in result  # Base video at 0:v
        assert "[1:v]format=rgba[ov_title]" in result
        assert "overlay=0:50" in result
        assert "format=nv12[outv]" in result
        assert "colorchannelmixer" not in result
    
    def test_logo_only(self):
        """Test minimal overlay with logo only."""
        result = build_minimal_encode_overlay_filter_complex(
            title_overlay_y=None,
            logo_enabled=True,
            logo_margin_px=5,
            logo_alpha=0.5,
        )
        assert "[0:v]" in result  # Base video
        # Logo at index 1 when no title
        assert "[1:v]format=rgba,colorchannelmixer=aa=0.5" in result
        assert "overlay=W-w-5:5" in result
        assert "format=nv12[outv]" in result
    
    def test_both_overlays(self):
        """Test minimal overlay with both title and logo."""
        result = build_minimal_encode_overlay_filter_complex(
            title_overlay_y=75,
            logo_enabled=True,
            logo_margin_px=8,
            logo_alpha=0.6,
        )
        # Logo at index 2 when title present
        assert "[2:v]format=rgba,colorchannelmixer=aa=0.6" in result
        assert "[1:v]format=rgba[ov_title]" in result  # Title at 1
        assert "overlay=0:75" in result  # Title overlay
        assert "format=nv12[outv]" in result
    
    def test_error_when_both_disabled(self):
        """Test that error is raised when both overlays disabled."""
        with pytest.raises(ValueError, match="requires at least title or logo"):
            build_minimal_encode_overlay_filter_complex(
                title_overlay_y=None,
                logo_enabled=False,
            )


class TestVideoLavfiConcatWithOverlay:
    """Test build_video_lavfi_audio_concat_filter_graph_with_title_overlay."""
    
    def test_title_only(self):
        """Test lavfi concat with title overlay only."""
        segments = [(0.0, 4.0)]
        result = build_video_lavfi_audio_concat_filter_graph_with_title_overlay(
            segments,
            overlay_y=120,
            logo_enabled=False,
        )
        # Inputs: 0=main video, 1=title PNG, 2=lavfi audio (no logo input)
        assert "[2:a]atrim=start=0:end=4.0" in result
        assert "[1:v]format=rgba[ov_title]" in result
        assert "overlay=0:120" in result
    
    def test_both_overlays(self):
        """Test lavfi concat with both title and logo overlays."""
        segments = [(0.0, 2.0), (5.0, 7.0)]
        result = build_video_lavfi_audio_concat_filter_graph_with_title_overlay(
            segments,
            overlay_y=80,
            logo_enabled=True,
            logo_margin_px=12,
            logo_alpha=0.85,
        )
        # Inputs: 0=video, 1=title, 2=logo, 3=lavfi audio
        assert "[3:a]atrim=start=0:end=2.0" in result  # First segment duration
        assert "[3:a]atrim=start=0:end=2.0" in result  # Second segment
        assert "[2:v]format=rgba,colorchannelmixer=aa=0.85" in result  # Logo
        assert "[1:v]format=rgba[ov_title]" in result  # Title
        assert "overlay=0:80" in result  # Title position
    
    def test_error_when_both_disabled(self):
        """Test that error is raised when both overlays disabled."""
        with pytest.raises(ValueError, match="cannot both be disabled"):
            build_video_lavfi_audio_concat_filter_graph_with_title_overlay(
                [(0.0, 1.0)],
                overlay_y=None,
                logo_enabled=False,
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
