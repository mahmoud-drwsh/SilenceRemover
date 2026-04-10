"""Tests for sr_media_manager package."""

import json
from pathlib import Path
from unittest.mock import Mock, patch
import pytest

from sr_media_manager import MediaManagerClient, sync_titles_from_api, ensure_audio_uploaded


class TestMediaManagerClient:
    """Test HTTP client initialization and methods."""
    
    def test_init_from_url(self):
        """Parse full URL correctly."""
        client = MediaManagerClient("https://example.com/TOKEN123/arabic-lessons/")
        assert client.base_url == "https://example.com"
        assert client.token == "TOKEN123"
        assert client.project == "arabic-lessons"
    
    def test_init_from_env(self, monkeypatch):
        """Read from MEDIA_MANAGER_URL env var."""
        monkeypatch.setenv("MEDIA_MANAGER_URL", "https://host.com/tok/proj/")
        client = MediaManagerClient()
        assert client.base_url == "https://host.com"
        assert client.token == "tok"
        assert client.project == "proj"
    
    def test_init_missing_url(self):
        """Raise error if no URL provided."""
        with pytest.raises(ValueError, match="MEDIA_MANAGER_URL"):
            MediaManagerClient()


class TestSyncTitlesFromApi:
    """Test title synchronization logic."""
    
    def test_sync_updates_different_titles(self, tmp_path):
        """When API title differs from local, update local and delete completed."""
        titles_dir = tmp_path / "titles"
        completed_dir = tmp_path / "completed"
        output_dir = tmp_path / "output"
        titles_dir.mkdir()
        completed_dir.mkdir()
        output_dir.mkdir()
        
        # Setup: local title is "Old"
        (titles_dir / "video.mp4.txt").write_text("Old")
        (completed_dir / "video.mp4.txt").write_text("done")
        
        # Mock API returns different title
        client = Mock()
        client.get_audio_files.return_value = [
            {"id": "video.mp4", "title": "New Title"}
        ]
        
        updated = sync_titles_from_api(client, titles_dir, completed_dir, output_dir)
        
        assert any(u[0] == "video.mp4" for u in updated)
        assert (titles_dir / "video.mp4.txt").read_text() == "New Title"
        assert not (completed_dir / "video.mp4.txt").exists()
    
    def test_sync_skips_same_titles(self, tmp_path):
        """When API title equals local, do nothing."""
        titles_dir = tmp_path / "titles"
        completed_dir = tmp_path / "completed"
        output_dir = tmp_path / "output"
        titles_dir.mkdir()
        completed_dir.mkdir()
        output_dir.mkdir()
        
        # Setup: local and API match
        (titles_dir / "video.mp4.txt").write_text("Same Title")
        (completed_dir / "video.mp4.txt").write_text("done")
        
        client = Mock()
        client.get_audio_files.return_value = [
            {"id": "video.mp4", "title": "Same Title"}
        ]
        
        updated = sync_titles_from_api(client, titles_dir, completed_dir, output_dir)
        
        assert "video.mp4" not in [u[0] for u in updated]
        assert (completed_dir / "video.mp4.txt").exists()  # Not deleted
    
    def test_sync_ignores_api_missing(self, tmp_path):
        """When API entry deleted, do nothing locally."""
        titles_dir = tmp_path / "titles"
        completed_dir = tmp_path / "completed"
        output_dir = tmp_path / "output"
        titles_dir.mkdir()
        completed_dir.mkdir()
        output_dir.mkdir()
        
        # Setup: local has file
        (titles_dir / "video.mp4.txt").write_text("Title")
        (completed_dir / "video.mp4.txt").write_text("done")
        
        # API returns empty (entry deleted)
        client = Mock()
        client.get_audio_files.return_value = []
        
        updated = sync_titles_from_api(client, titles_dir, completed_dir, output_dir)
        
        assert len(updated) == 0
        assert (titles_dir / "video.mp4.txt").exists()  # Preserved
        assert (completed_dir / "video.mp4.txt").exists()  # Preserved
    
    def test_sync_api_failure_safe(self, tmp_path):
        """When API fails, return empty list (fail-safe)."""
        client = Mock()
        client.get_audio_files.side_effect = Exception("Network error")
        
        updated = sync_titles_from_api(client, tmp_path / "titles", tmp_path / "completed", tmp_path / "output")
        
        assert updated == []  # Safe fallback


class TestEnsureAudioUploaded:
    """Test idempotent upload logic."""
    
    def test_upload_if_not_exists(self, tmp_path):
        """Upload when file not on server."""
        audio_file = tmp_path / "snippet.ogg"
        audio_file.write_text("fake audio data")
        
        client = Mock()
        client.check_exists.return_value = False
        client.upload_audio.return_value = True
        
        result = ensure_audio_uploaded(client, "video.mp4", "Title", audio_file)
        
        assert result is True
        client.upload_audio.assert_called_once()
    
    def test_skip_if_exists(self, tmp_path):
        """Skip upload when file already on server."""
        audio_file = tmp_path / "snippet.ogg"
        audio_file.write_text("fake audio data")
        
        client = Mock()
        client.check_exists.return_value = True
        
        result = ensure_audio_uploaded(client, "video.mp4", "Title", audio_file)
        
        assert result is True
        client.upload_audio.assert_not_called()
    
    def test_error_handling(self, tmp_path):
        """Return False on error, don't raise."""
        audio_file = tmp_path / "snippet.ogg"
        audio_file.write_text("fake audio data")
        
        client = Mock()
        client.check_exists.side_effect = Exception("API down")
        
        result = ensure_audio_uploaded(client, "video.mp4", "Title", audio_file)
        
        assert result is False


class TestVideoOverwrite:
    """Test video auto-overwrite feature - check_video_exists, upload_video with skip_if_exists_with_title."""
    
    def test_check_video_exists_not_found(self):
        """Test 1: check_video_exists() - not found returns (False, False)."""
        client = Mock()
        # Mock empty response for get with title filter
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.status_code = 200
        client._client.get.return_value = mock_response
        
        # Also mock check_exists to return False
        client.check_exists.return_value = False
        
        # Call check_video_exists (assumed new method)
        result = client.check_video_exists("test-vid", "Any Title")
        
        assert result == (False, False)
    
    def test_check_video_exists_found_matching_title(self):
        """Test 2: check_video_exists() - found with matching title returns (True, True)."""
        client = Mock()
        
        # Mock response with matching title
        mock_response = Mock()
        mock_response.json.return_value = [{"id": "vid", "title": "Match"}]
        mock_response.status_code = 200
        client._client.get.return_value = mock_response
        
        result = client.check_video_exists("vid", "Match")
        
        assert result == (True, True)
    
    def test_check_video_exists_found_different_title(self):
        """Test 3: check_video_exists() - found with different title returns (True, False)."""
        client = Mock()
        
        # First call: get with title filter returns empty (no match)
        # Second call: check_exists returns True
        empty_response = Mock()
        empty_response.json.return_value = []
        
        match_response = Mock()
        match_response.json.return_value = [{"id": "vid", "title": "Different"}]
        
        client._client.get.side_effect = [empty_response, match_response]
        client.check_exists.return_value = True
        
        result = client.check_video_exists("vid", "Expected Title")
        
        assert result == (True, False)
    
    def test_upload_video_skip_if_exists_exact_match(self):
        """Test 4: upload_video() with skip_if_exists_with_title=True - exact match skips."""
        client = Mock()
        
        # Mock check_video_exists returns (exists=True, title_matches=True)
        client.check_video_exists.return_value = (True, True)
        
        # Call upload_video with skip flag
        result = client.upload_video(
            "vid", 
            "Same Title", 
            Path("/fake/path.mp4"),
            skip_if_exists_with_title=True
        )
        
        # Assert: should not call POST, return skipped=True
        client._client.post.assert_not_called()
        assert result.get("skipped") is True
        assert result.get("uploaded") is False
    
    def test_upload_video_skip_if_exists_will_overwrite(self):
        """Test 5: upload_video() with skip_if_exists_with_title=True - different title triggers overwrite."""
        client = Mock()
        
        # Mock check_video_exists returns (exists=True, title_matches=False)
        client.check_video_exists.return_value = (True, False)
        
        # Mock POST returns 200 with overwritten:true
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "overwritten": True, "id": "vid"}
        client._client.post.return_value = mock_response
        
        # Need to mock file existence for ProgressFile
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.stat') as mock_stat:
                mock_stat.return_value = Mock(st_size=1000)
                with patch('builtins.open', mock_open := Mock()):
                    mock_open.return_value.__enter__ = Mock(return_value=Mock(read=Mock(return_value=b'')))
                    mock_open.return_value.__exit__ = Mock(return_value=False)
                    
                    result = client.upload_video(
                        "vid",
                        "New Title",
                        Path("/fake/path.mp4"),
                        skip_if_exists_with_title=True
                    )
        
        assert result.get("overwritten") is True
        assert result.get("uploaded") is True
    
    def test_check_uploaded_with_title_same_title(self):
        """Test 6: check_uploaded_with_title() helper - video exists, same title."""
        client = Mock()
        
        # Mock check_video_exists returns (exists=True, title_matches=True)
        client.check_video_exists.return_value = (True, True)
        
        # Call check_uploaded_with_title (assumed new helper)
        result = client.check_uploaded_with_title("vid", "Same Title")
        
        assert result.get("should_upload") is False
        assert result.get("will_overwrite") is False
        assert result.get("exists") is True
    
    def test_check_uploaded_with_title_different_title(self):
        """Test 7: check_uploaded_with_title() helper - video exists, different title."""
        client = Mock()
        
        # Mock check_video_exists returns (exists=True, title_matches=False)
        client.check_video_exists.return_value = (True, False)
        
        # Call check_uploaded_with_title
        result = client.check_uploaded_with_title("vid", "Different Title")
        
        assert result.get("should_upload") is True
        assert result.get("will_overwrite") is True
        assert result.get("exists") is True
