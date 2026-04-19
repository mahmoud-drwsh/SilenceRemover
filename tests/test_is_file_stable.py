"""Unit tests for Windows input lock filtering."""

import sys
from pathlib import Path
from unittest.mock import patch

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

import pytest

from src.core.cli import collect_video_files
from src.core.constants import VIDEO_EXTENSIONS
from src.core.fs_utils import is_file_locked


class TestIsFileLocked:
    """Test Windows lock detection helper."""

    def test_returns_false_on_non_windows(self, tmp_path):
        video_file = tmp_path / "video.mp4"
        video_file.write_text("content")

        with patch("src.core.fs_utils._IS_WINDOWS", False):
            assert is_file_locked(video_file) is False

    def test_returns_true_for_windows_sharing_violation(self, tmp_path):
        video_file = tmp_path / "video.mp4"
        video_file.write_text("content")

        with (
            patch("src.core.fs_utils._IS_WINDOWS", True),
            patch("src.core.fs_utils._CreateFileW", return_value="INVALID"),
            patch("src.core.fs_utils._INVALID_HANDLE_VALUE", "INVALID"),
            patch("src.core.fs_utils._ERROR_SHARING_VIOLATION", 32),
            patch("src.core.fs_utils._ERROR_LOCK_VIOLATION", 33),
            patch("src.core.fs_utils.ctypes.get_last_error", return_value=32, create=True),
        ):
            assert is_file_locked(video_file) is True

    def test_returns_false_when_windows_open_succeeds(self, tmp_path):
        video_file = tmp_path / "video.mp4"
        video_file.write_text("content")

        with (
            patch("src.core.fs_utils._IS_WINDOWS", True),
            patch("src.core.fs_utils._CreateFileW", return_value="HANDLE"),
            patch("src.core.fs_utils._INVALID_HANDLE_VALUE", "INVALID"),
            patch("src.core.fs_utils._CloseHandle") as close_handle,
        ):
            assert is_file_locked(video_file) is False
            close_handle.assert_called_once_with("HANDLE")


class TestCollectVideoFiles:
    """Test startup video collection and filtering."""

    def test_filters_locked_video_files(self, tmp_path, capsys):
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        (input_dir / "aaa.mp4").write_text("content")
        (input_dir / "bbb.mp4").write_text("content")
        (input_dir / "notes.txt").write_text("not a video")

        def mock_locked(path: Path) -> bool:
            return path.name == "bbb.mp4"

        with patch("src.core.cli.is_file_locked", side_effect=mock_locked):
            result = collect_video_files(input_dir)

        assert [path.name for path in result] == ["aaa.mp4"]
        captured = capsys.readouterr()
        assert "bbb.mp4" in captured.out
        assert "Skipping locked input video(s)" in captured.out

    def test_returns_sorted_list_for_unlocked_videos(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        (input_dir / "zebra.mp4").write_text("z")
        (input_dir / "alpha.mp4").write_text("a")
        (input_dir / "beta.mp4").write_text("b")

        with patch("src.core.cli.is_file_locked", return_value=False):
            result = collect_video_files(input_dir)

        assert [p.name for p in result] == ["alpha.mp4", "beta.mp4", "zebra.mp4"]

    def test_ignores_non_video_files(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        (input_dir / "video.mp4").write_text("v")
        (input_dir / "image.jpg").write_text("i")
        (input_dir / "document.pdf").write_text("d")

        with patch("src.core.cli.is_file_locked", return_value=False):
            result = collect_video_files(input_dir)

        assert [p.name for p in result] == ["video.mp4"]

    def test_ignores_directories(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        (input_dir / "video.mp4").write_text("v")
        (input_dir / "subdir").mkdir()
        (input_dir / "subdir" / "nested.mp4").write_text("n")

        with patch("src.core.cli.is_file_locked", return_value=False):
            result = collect_video_files(input_dir)

        assert [p.name for p in result] == ["video.mp4"]


class TestVideoExtensionsCoverage:
    """Test that all configured video extensions are recognized."""

    @pytest.mark.parametrize("ext", VIDEO_EXTENSIONS)
    def test_all_video_extensions_recognized(self, tmp_path, ext):
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        video_file = input_dir / f"test{ext}"
        video_file.write_text("fake content")

        with patch("src.core.cli.is_file_locked", return_value=False):
            result = collect_video_files(input_dir)

        assert [p.name for p in result] == [f"test{ext}"]


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_directory_returns_empty_list(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        result = collect_video_files(input_dir)
        assert result == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
