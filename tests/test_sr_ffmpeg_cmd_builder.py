"""Unit tests for sr_ffmpeg_cmd_builder package.

Tests for FFmpeg/FFprobe command building - pure functions with no subprocess calls.
"""

import sys
from pathlib import Path

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

import pytest

from sr_ffmpeg_cmd_builder import (
    build_encoder_probe_command,
    build_ffprobe_format_json_command,
    build_ffprobe_has_audio_command,
    build_ffprobe_metadata_command,
    build_ffprobe_stream_dimensions_command,
)


class TestBuildEncoderProbeCommand:
    """Test encoder probe command builder."""
    
    def test_returns_list(self):
        """Test that function returns a list."""
        result = build_encoder_probe_command("libx264")
        assert isinstance(result, list)
    
    def test_contains_ffmpeg_binary(self):
        """Test that command starts with ffmpeg."""
        result = build_encoder_probe_command("libx264")
        assert result[0] == "ffmpeg"
    
    def test_contains_codec(self):
        """Test that codec is in command."""
        result = build_encoder_probe_command("libx264")
        assert "libx264" in result
        assert "-c:v" in result
    
    def test_contains_pix_fmt(self):
        """Test that pixel format is specified."""
        result = build_encoder_probe_command("libx264")
        assert "-pix_fmt" in result
        assert "yuv420p" in result
    
    def test_contains_lavfi_input(self):
        """Test that lavfi test pattern is used."""
        result = build_encoder_probe_command("libx264")
        assert "-f" in result
        assert "lavfi" in result
        assert "testsrc=duration=1:size=320x240" in result
    
    def test_contains_frame_limit(self):
        """Test that frame limit is set."""
        result = build_encoder_probe_command("libx264")
        assert "-frames:v" in result
        assert "25" in result
    
    def test_contains_output_to_null(self):
        """Test that output goes to null."""
        result = build_encoder_probe_command("libx264")
        assert "-f" in result
        assert "null" in result
        assert result[-1] == "-"
    
    def test_different_codecs(self):
        """Test with different codec names."""
        for codec in ["libx264", "libx265", "hevc_qsv", "h264_nvenc"]:
            result = build_encoder_probe_command(codec)
            assert codec in result
    
    def test_empty_codec_args(self):
        """Test with empty codec args."""
        result = build_encoder_probe_command("libx264", ())
        assert isinstance(result, list)
    
    def test_with_codec_args(self):
        """Test with additional codec arguments."""
        extra_args = ["-preset", "slow", "-crf", "23"]
        result = build_encoder_probe_command("libx264", extra_args)
        # Check that extra args are included
        for arg in extra_args:
            assert arg in result


class TestBuildFfprobeMetadataCommand:
    """Test FFprobe metadata command builder."""
    
    def test_returns_list(self):
        """Test that function returns a list."""
        result = build_ffprobe_metadata_command(Path("video.mp4"), "duration")
        assert isinstance(result, list)
    
    def test_contains_ffprobe_binary(self):
        """Test that command starts with ffprobe."""
        result = build_ffprobe_metadata_command(Path("video.mp4"), "duration")
        assert result[0] == "ffprobe"
    
    def test_contains_input_file(self):
        """Test that input file is included."""
        input_path = Path("/path/to/video.mp4")
        result = build_ffprobe_metadata_command(input_path, "duration")
        assert str(input_path) in result
    
    def test_contains_format_entry(self):
        """Test that format entry is included."""
        result = build_ffprobe_metadata_command(Path("video.mp4"), "duration")
        assert "-show_entries" in result
        assert "format=duration" in result
    
    def test_different_format_entries(self):
        """Test with different format entries."""
        entries = ["duration", "bit_rate", "size", "format_name"]
        for entry in entries:
            result = build_ffprobe_metadata_command(Path("video.mp4"), entry)
            assert f"format={entry}" in result
    
    def test_contains_output_format(self):
        """Test that output format is specified."""
        result = build_ffprobe_metadata_command(Path("video.mp4"), "duration")
        assert "-of" in result
        assert "default=nw=1:nk=1" in result


class TestBuildFfprobeStreamDimensionsCommand:
    """Test FFprobe stream dimensions command builder."""
    
    def test_returns_list(self):
        """Test that function returns a list."""
        result = build_ffprobe_stream_dimensions_command(Path("video.mp4"))
        assert isinstance(result, list)
    
    def test_contains_ffprobe_binary(self):
        """Test that command starts with ffprobe."""
        result = build_ffprobe_stream_dimensions_command(Path("video.mp4"))
        assert result[0] == "ffprobe"
    
    def test_contains_input_file(self):
        """Test that input file is included."""
        input_path = Path("/path/to/video.mp4")
        result = build_ffprobe_stream_dimensions_command(input_path)
        assert str(input_path) in result
    
    def test_selects_video_stream(self):
        """Test that video stream is selected."""
        result = build_ffprobe_stream_dimensions_command(Path("video.mp4"))
        assert "-select_streams" in result
        assert "v:0" in result
    
    def test_queries_width_height(self):
        """Test that width and height are queried."""
        result = build_ffprobe_stream_dimensions_command(Path("video.mp4"))
        assert "-show_entries" in result
        assert "stream=width,height" in result
    
    def test_csv_output_format(self):
        """Test that CSV output format is used."""
        result = build_ffprobe_stream_dimensions_command(Path("video.mp4"))
        assert "-of" in result
        assert "csv=p=0:nk=1" in result


class TestBuildFfprobeHasAudioCommand:
    """Test FFprobe has audio command builder."""
    
    def test_returns_list(self):
        """Test that function returns a list."""
        result = build_ffprobe_has_audio_command(Path("video.mp4"))
        assert isinstance(result, list)
    
    def test_contains_ffprobe_binary(self):
        """Test that command starts with ffprobe."""
        result = build_ffprobe_has_audio_command(Path("video.mp4"))
        assert result[0] == "ffprobe"
    
    def test_contains_input_file(self):
        """Test that input file is included."""
        input_path = Path("/path/to/video.mp4")
        result = build_ffprobe_has_audio_command(input_path)
        assert str(input_path) in result
    
    def test_selects_audio_streams(self):
        """Test that audio streams are selected."""
        result = build_ffprobe_has_audio_command(Path("video.mp4"))
        assert "-select_streams" in result
        assert "a" in result
    
    def test_queries_stream_index(self):
        """Test that stream index is queried."""
        result = build_ffprobe_has_audio_command(Path("video.mp4"))
        assert "-show_entries" in result
        assert "stream=index" in result
    
    def test_csv_output_format(self):
        """Test that CSV output format is used."""
        result = build_ffprobe_has_audio_command(Path("video.mp4"))
        assert "-of" in result
        assert "csv=p=0" in result


class TestBuildFfprobeFormatJsonCommand:
    """Test FFprobe format JSON command builder."""
    
    def test_returns_list(self):
        """Test that function returns a list."""
        result = build_ffprobe_format_json_command(Path("video.mp4"))
        assert isinstance(result, list)
    
    def test_contains_ffprobe_binary(self):
        """Test that command starts with ffprobe."""
        result = build_ffprobe_format_json_command(Path("video.mp4"))
        assert result[0] == "ffprobe"
    
    def test_contains_input_file(self):
        """Test that input file is included."""
        input_path = Path("/path/to/video.mp4")
        result = build_ffprobe_format_json_command(input_path)
        assert str(input_path) in result
    
    def test_json_output_format(self):
        """Test that JSON output format is specified."""
        result = build_ffprobe_format_json_command(Path("video.mp4"))
        assert "-print_format" in result
        assert "json" in result
    
    def test_shows_format(self):
        """Test that format info is requested."""
        result = build_ffprobe_format_json_command(Path("video.mp4"))
        assert "-show_format" in result
    
    def test_quiet_mode(self):
        """Test that quiet mode is enabled."""
        result = build_ffprobe_format_json_command(Path("video.mp4"))
        assert "-v" in result
        assert "quiet" in result


class TestCommandStructure:
    """Test general command structure and ordering."""
    
    def test_encoder_probe_order(self):
        """Test that encoder probe command has reasonable structure."""
        result = build_encoder_probe_command("libx264", ["-preset", "fast"])
        # ffmpeg should be first
        assert result[0] == "ffmpeg"
        # -v error should appear early
        assert "-v" in result[:5]
        # -c:v codec should be present
        assert "-c:v" in result
        codec_idx = result.index("-c:v")
        assert result[codec_idx + 1] == "libx264"
        # Output should be at the end
        assert result[-3] == "-f"
        assert result[-2] == "null"
        assert result[-1] == "-"
    
    def test_ffprobe_metadata_order(self):
        """Test that metadata command has reasonable structure."""
        result = build_ffprobe_metadata_command(Path("video.mp4"), "duration")
        # ffprobe should be first
        assert result[0] == "ffprobe"
        # -v error should be early
        assert result[1] == "-v"
        assert result[2] == "error"
        # Input file should be last
        assert result[-1] == str(Path("video.mp4"))
    
    def test_all_commands_are_lists_of_strings(self):
        """Test that all commands return lists of strings."""
        builders = [
            lambda: build_encoder_probe_command("libx264"),
            lambda: build_ffprobe_metadata_command(Path("v.mp4"), "duration"),
            lambda: build_ffprobe_stream_dimensions_command(Path("v.mp4")),
            lambda: build_ffprobe_has_audio_command(Path("v.mp4")),
            lambda: build_ffprobe_format_json_command(Path("v.mp4")),
        ]
        for builder in builders:
            result = builder()
            assert isinstance(result, list)
            for item in result:
                assert isinstance(item, str)


class TestEdgeCases:
    """Test edge cases and special inputs."""
    
    def test_encoder_with_special_codec_name(self):
        """Test encoder probe with codec names containing special chars."""
        # Some codecs might have underscores or numbers
        result = build_encoder_probe_command("h264_nvenc")
        assert "h264_nvenc" in result
    
    def test_ffprobe_with_path_containing_spaces(self):
        """Test ffprobe with path containing spaces."""
        path = Path("/path/with spaces/video.mp4")
        result = build_ffprobe_metadata_command(path, "duration")
        # Path should be included as-is (caller handles quoting)
        assert str(path) in result
    
    def test_ffprobe_with_unicode_path(self):
        """Test ffprobe with unicode path."""
        path = Path("/path/مرحبا/video.mp4")
        result = build_ffprobe_metadata_command(path, "duration")
        assert str(path) in result
    
    def test_empty_codec_args_sequence(self):
        """Test encoder probe with empty codec args."""
        result = build_encoder_probe_command("libx264", [])
        assert isinstance(result, list)
        assert "libx264" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
