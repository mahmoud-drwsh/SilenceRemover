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
