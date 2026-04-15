"""Unit tests for file stability detection functions.

Tests for is_file_stable() and collect_video_files() in src/core/cli.py.
These functions detect files being written to (e.g., during recording).
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

import pytest

from src.core.cli import collect_video_files, is_file_stable
from src.core.constants import AUDIO_FILE_EXT, VIDEO_EXTENSIONS
from src.core.paths import get_snippet_path, is_snippet_done


class TestIsFileStable:
    """Test is_file_stable() function."""

    def test_valid_video_file_returns_true(self, sample_vertical):
        """Test 1: Valid video file returns True (happy path).

        Uses actual ffprobe call to verify a real video file is detected as stable.
        """
        assert is_file_stable(sample_vertical) is True

    def test_nonexistent_file_returns_false(self):
        """Test 2: Non-existent file returns False (edge case).

        Files that don't exist should be considered unstable.
        """
        nonexistent = Path("/tmp/definitely_does_not_exist_12345.mp4")
        assert is_file_stable(nonexistent) is False

    def test_text_file_returns_false(self, tmp_path):
        """Test 3: Text file returns False (not a video).

        Non-video files should fail ffprobe check and return False.
        """
        text_file = tmp_path / "not_a_video.txt"
        text_file.write_text("This is not a video file")
        assert is_file_stable(text_file) is False

    def test_empty_file_returns_false(self, tmp_path):
        """Test: Empty file returns False.

        Empty files should fail ffprobe duration check.
        """
        empty_file = tmp_path / "empty.mp4"
        empty_file.write_text("")
        assert is_file_stable(empty_file) is False


class TestCollectVideoFiles:
    """Test collect_video_files() function."""

    def test_filters_unstable_files(self, tmp_path):
        """Test 4: collect_video_files filters unstable files.

        Only stable video files should be returned; unstable ones should be skipped.
        """
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # Create video files
        (input_dir / "aaa.mp4").write_text("content")
        (input_dir / "bbb.mp4").write_text("content")

        # Create a text file (should be ignored regardless)
        (input_dir / "notes.txt").write_text("not a video")

        # Track calls and return True for aaa, False for bbb
        def mock_check(path):
            mock_check.calls.append(path.name)
            return path.name == "aaa.mp4"

        mock_check.calls = []

        with patch("src.core.cli.is_file_stable", side_effect=mock_check):
            result = collect_video_files(input_dir)

        # Only aaa.mp4 should be returned (stable)
        assert len(result) == 1
        assert result[0].name == "aaa.mp4"
        # Both video files should have been checked
        assert "aaa.mp4" in mock_check.calls
        assert "bbb.mp4" in mock_check.calls

    def test_skips_snippet_files_no_ffprobe_check(self, tmp_path):
        """Test 5: collect_video_files skips files with audio extracted (no ffprobe check).

        Files with existing snippet (audio already extracted) should be skipped
        without calling is_file_stable.
        """
        # Setup: input/ and output/temp/ directories
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        temp_dir = tmp_path / "output" / "temp"
        temp_dir.mkdir(parents=True)

        # Create video files
        (input_dir / "has_snippet.mp4").write_text("content")
        (input_dir / "new.mp4").write_text("content")

        # Create snippet file for one video (simulates audio already extracted)
        snippet_dir = temp_dir / "snippet"
        snippet_dir.mkdir(parents=True, exist_ok=True)
        snippet_path = snippet_dir / f"has_snippet{AUDIO_FILE_EXT}"
        snippet_path.write_text("fake audio content")
        assert is_snippet_done(temp_dir, "has_snippet") is True

        # Track which files were checked for stability
        checked_files = []

        def mock_is_stable(path):
            checked_files.append(path.name)
            return True

        # Patch at the module level where is_file_stable is looked up
        with patch("src.core.cli.is_file_stable", side_effect=mock_is_stable):
            result = collect_video_files(input_dir)

        # Only new.mp4 should have been checked (has_snippet.mp4 skipped)
        assert "new.mp4" in checked_files
        assert "has_snippet.mp4" not in checked_files
        assert len(result) == 1
        assert result[0].name == "new.mp4"

    def test_checks_stability_for_new_files_only(self, tmp_path):
        """Test 6: collect_video_files checks stability for new files only.

        Verify ffprobe is only called for files without extracted audio.
        """
        # Create directory structure
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        temp_dir = output_dir / "temp"
        temp_dir.mkdir()

        # Create multiple video files
        video1 = input_dir / "video1.mp4"
        video1.write_text("fake content 1")
        video2 = input_dir / "video2.mp4"
        video2.write_text("fake content 2")
        video3 = input_dir / "video3.mp4"
        video3.write_text("fake content 3")

        # Create snippet file for video2 (audio already extracted)
        snippet_dir = temp_dir / "snippet"
        snippet_dir.mkdir(parents=True, exist_ok=True)
        snippet_path = snippet_dir / f"video2{AUDIO_FILE_EXT}"
        snippet_path.write_text("fake audio content")

        # Track which files were checked for stability
        checked_files = []

        def mock_is_file_stable(path):
            checked_files.append(path.name)
            return True

        with patch("src.core.cli.is_file_stable", side_effect=mock_is_file_stable):
            result = collect_video_files(input_dir)

        # Only video1 and video3 should have been checked (video2 was skipped)
        assert "video1.mp4" in checked_files
        assert "video3.mp4" in checked_files
        assert "video2.mp4" not in checked_files

        # All videos without snippets should be in result
        result_names = {p.name for p in result}
        assert "video1.mp4" in result_names
        assert "video3.mp4" in result_names
        assert "video2.mp4" not in result_names

    def test_returns_sorted_list(self, tmp_path):
        """Test: Results are returned in sorted order."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # Create videos in non-alphabetical order
        (input_dir / "zebra.mp4").write_text("z")
        (input_dir / "alpha.mp4").write_text("a")
        (input_dir / "beta.mp4").write_text("b")

        with patch("src.core.cli.is_file_stable", return_value=True):
            result = collect_video_files(input_dir)

        # Results should be sorted alphabetically
        names = [p.name for p in result]
        assert names == ["alpha.mp4", "beta.mp4", "zebra.mp4"]

    def test_ignores_non_video_files(self, tmp_path):
        """Test: Non-video files are ignored."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # Create video and non-video files
        (input_dir / "video.mp4").write_text("v")
        (input_dir / "image.jpg").write_text("i")
        (input_dir / "document.pdf").write_text("d")
        (input_dir / "data.json").write_text("j")

        with patch("src.core.cli.is_file_stable", return_value=True):
            result = collect_video_files(input_dir)

        # Only video files should be returned
        assert len(result) == 1
        assert result[0].name == "video.mp4"

    def test_ignores_directories(self, tmp_path):
        """Test: Directories are ignored."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # Create video file and subdirectory
        (input_dir / "video.mp4").write_text("v")
        (input_dir / "subdir").mkdir()
        (input_dir / "subdir" / "nested.mp4").write_text("n")

        with patch("src.core.cli.is_file_stable", return_value=True):
            result = collect_video_files(input_dir)

        # Only top-level video files should be returned
        assert len(result) == 1
        assert result[0].name == "video.mp4"


class TestVideoExtensionsCoverage:
    """Test that all video extensions are recognized."""

    @pytest.mark.parametrize("ext", VIDEO_EXTENSIONS)
    def test_all_video_extensions_recognized(self, tmp_path, ext):
        """Test: All configured video extensions are recognized."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        video_file = input_dir / f"test{ext}"
        video_file.write_text("fake content")

        with patch("src.core.cli.is_file_stable", return_value=True):
            result = collect_video_files(input_dir)

        assert len(result) == 1
        assert result[0].name == f"test{ext}"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_directory_returns_empty_list(self, tmp_path):
        """Test: Empty directory returns empty list."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        result = collect_video_files(input_dir)
        assert result == []

    def test_is_file_stable_handles_exception(self, tmp_path):
        """Test: is_file_stable handles exceptions gracefully."""
        video_file = tmp_path / "video.mp4"
        video_file.write_text("content")

        # Mock run to raise an exception
        with patch("src.ffmpeg.runner.run", side_effect=Exception("FFmpeg error")):
            result = is_file_stable(video_file)
            assert result is False

    def test_is_file_stable_handles_timeout(self, tmp_path):
        """Test: is_file_stable handles timeout gracefully."""
        video_file = tmp_path / "video.mp4"
        video_file.write_text("content")

        # Mock run to raise timeout
        with patch("src.ffmpeg.runner.run", side_effect=TimeoutError("Timeout")):
            result = is_file_stable(video_file)
            assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
