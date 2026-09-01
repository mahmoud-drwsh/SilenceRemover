"""Tests for sr_media_manager package."""

import json
from pathlib import Path
from unittest.mock import Mock, patch
import httpx
import pytest

from sr_media_manager import (
    MediaManagerClient,
    sync_titles_from_api,
    ensure_audio_uploaded,
    get_uploaded_video_ids,
    check_uploaded_with_title,
)
from sr_media_manager.api import ProgressFile, VIDEO_UPLOAD_TIMEOUT


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

    def test_get_video_files_can_include_trash(self):
        """All-list existence checks can include trash with one request."""
        with patch("httpx.Client") as http_client:
            response = Mock()
            response.json.return_value = []
            http_client.return_value.get.return_value = response

            client = MediaManagerClient("https://example.com/projects/TOKEN123/lessons/")
            client.get_video_files(include_trash=True)

        requested_url = http_client.return_value.get.call_args.args[0]
        assert "include_trash=true" in requested_url
        assert "include_pending=true" not in requested_url

    def test_update_tags_rejects_non_2xx_response(self):
        client = MediaManagerClient("https://example.com/projects/TOKEN123/lessons/")
        client._client = Mock()
        client._client.put.return_value = httpx.Response(
            503,
            request=httpx.Request("PUT", "https://example.com/api/files/file-1?type=audio"),
        )

        with pytest.raises(Exception, match="Tag update failed.*503"):
            client.update_tags("file-1", ["trash"])

    def test_delete_file_rejects_non_2xx_response(self):
        client = MediaManagerClient("https://example.com/projects/TOKEN123/lessons/")
        client._client = Mock()
        client._client.put.return_value = httpx.Response(
            200,
            request=httpx.Request("PUT", "https://example.com/api/files/file-1?type=video"),
        )
        client._client.delete.return_value = httpx.Response(
            503,
            request=httpx.Request("DELETE", "https://example.com/api/files/file-1?type=video"),
        )

        with pytest.raises(Exception, match="Delete failed.*503"):
            client.delete_file("file-1", "video")

    def test_uploaded_video_ids_use_virtual_all_list(self):
        """Phase 9 should use the all list plus trash inclusion for idempotency."""
        client = Mock()
        client.get_video_files.return_value = [{"id": "already-pending", "tags": ["pending"]}]

        assert get_uploaded_video_ids(client) == ["already-pending"]
        client.get_video_files.assert_called_once_with(include_trash=True)

    def test_progress_file_preserves_multipart_content_length(self, tmp_path):
        """Progress wrapper must not force chunked uploads through reverse proxies."""
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"fake video")

        with ProgressFile(video_path, None, video_path.stat().st_size) as pf:
            request = httpx.Request(
                "POST",
                "https://example.com/upload",
                data={"id": "vid"},
                files={"file": ("video.mp4", pf, "video/mp4")},
            )

        assert "content-length" in request.headers
        assert request.headers.get("transfer-encoding") != "chunked"

    def test_upload_original_uses_presigned_parts_and_checksum(self, tmp_path):
        original = tmp_path / "source.mp4"
        original.write_bytes(b"original-video-bytes")
        client = MediaManagerClient("https://example.com/projects/TOKEN123/lessons/")
        client._client = Mock()
        initiated = Mock()
        initiated.json.return_value = {
            "session_id": "session-1", "upload_id": "upload-1", "part_size": 8 * 1024 * 1024,
            "urls": ["https://object.example/part-1"],
        }
        completed = Mock()
        client._client.post.side_effect = [initiated, completed]
        part = Mock()
        part.headers = {"etag": '"etag-1"'}

        progress: list[tuple[int, int]] = []
        with patch("sr_media_manager.api.httpx.put", return_value=part) as put:
            assert client.upload_original("source-1", original, lambda done, total: progress.append((done, total))) is True

        init_payload = client._client.post.call_args_list[0].kwargs["json"]
        assert init_payload["checksum_sha256"] == __import__("hashlib").sha256(original.read_bytes()).hexdigest()
        assert put.call_args.kwargs["content"] == original.read_bytes()
        assert progress == [(original.stat().st_size, original.stat().st_size)]
        assert client._client.post.call_args_list[0].args[0].endswith("/api/uploads/initiate")
        assert client._client.post.call_args_list[1].args[0].endswith("/api/uploads/session-1/complete")
        assert client._client.post.call_args_list[1].kwargs["json"] == {"parts": [{"part_number": 1, "etag": '"etag-1"'}]}

    def test_analyze_ogg_snippet_uses_authenticated_transient_multipart_request(self, tmp_path):
        snippet = tmp_path / "snippet.ogg"
        snippet.write_bytes(b"OggSsnippet")
        client = MediaManagerClient("https://example.com/projects/TOKEN123/lessons/")
        client._client = Mock()
        response = Mock()
        response.json.return_value = {"ok": True, "transcript": "نص", "title": "عنوان الدرس"}
        client._client.post.return_value = response

        assert client.analyze_ogg_snippet(snippet) == ("نص", "عنوان الدرس")
        call = client._client.post.call_args
        assert call.args[0].endswith("/api/snippet-analysis")
        assert call.kwargs["files"]["snippet"][0] == "snippet.ogg"
        assert call.kwargs["files"]["snippet"][2] == "audio/ogg"
        assert "json" not in call.kwargs

    def test_analyze_ogg_snippet_rejects_non_ogg_without_request(self, tmp_path):
        snippet = tmp_path / "snippet.mp3"
        snippet.write_bytes(b"audio")
        client = MediaManagerClient("https://example.com/projects/TOKEN123/lessons/")
        client._client = Mock()

        with pytest.raises(Exception, match="requires an OGG"):
            client.analyze_ogg_snippet(snippet)
        client._client.post.assert_not_called()

    def test_upload_overlay_logo_if_missing_uses_presigned_r2_transport(self, tmp_path):
        logo = tmp_path / "logo.png"
        logo.write_bytes(b"\x89PNG\r\n\x1a\nlogo")
        client = MediaManagerClient("https://example.com/projects/TOKEN123/lessons/")
        client._client = Mock()
        initiated = Mock()
        initiated.json.return_value = {"ok": True, "upload_url": "https://objects.example/logo"}
        completed = Mock()
        completed.json.return_value = {"ok": True, "uploaded": True}
        client._client.post.side_effect = [initiated, completed]
        r2_response = Mock()

        with patch("sr_media_manager.api.httpx.put", return_value=r2_response) as put:
            assert client.upload_overlay_logo_if_missing(logo) is True

        assert client._client.post.call_args_list[0].args[0].endswith("/api/overlay-logo-if-missing/initiate")
        assert client._client.post.call_args_list[1].args[0].endswith("/api/overlay-logo-if-missing/complete")
        assert put.call_args.args[0] == "https://objects.example/logo"
        assert put.call_args.kwargs["content"] == logo.read_bytes()

    def test_upload_overlay_logo_if_missing_retries_connection_reset(self, tmp_path, monkeypatch):
        logo = tmp_path / "logo.png"
        logo.write_bytes(b"\x89PNG\r\n\x1a\nlogo")
        client = MediaManagerClient("https://example.com/projects/TOKEN123/lessons/")
        client._client = Mock()
        initiated = Mock()
        initiated.json.return_value = {"ok": True, "upload_url": "https://objects.example/logo"}
        complete = Mock()
        complete.json.return_value = {"ok": True, "uploaded": False}
        client._client.post.side_effect = [initiated, initiated, complete]
        monkeypatch.setattr("sr_media_manager.api.time.sleep", lambda _seconds: None)

        with patch("sr_media_manager.api.httpx.put", side_effect=[httpx.ReadError("reset"), Mock()] ) as put:
            assert client.upload_overlay_logo_if_missing(logo) is False
        assert put.call_count == 2

    def test_upload_original_aborts_session_after_part_failure(self, tmp_path):
        original = tmp_path / "source.mp4"
        original.write_bytes(b"original-video-bytes")
        client = MediaManagerClient("https://example.com/projects/TOKEN123/lessons/")
        client._client = Mock()
        initiated = Mock()
        initiated.json.return_value = {
            "session_id": "session-1", "upload_id": "upload-1", "part_size": 8 * 1024 * 1024,
            "urls": ["https://object.example/part-1"],
        }
        client._client.post.return_value = initiated

        with patch("sr_media_manager.api.httpx.put", side_effect=httpx.HTTPError("network")):
            with pytest.raises(Exception, match="original upload failed"):
                client.upload_original("source-1", original)

        assert client._client.post.call_args_list[1].args[0].endswith("/api/uploads/session-1/abort")

    def test_upload_completion_error_includes_server_detail(self, tmp_path):
        original = tmp_path / "source.mp4"
        original.write_bytes(b"original-video-bytes")
        client = MediaManagerClient("https://example.com/projects/TOKEN123/lessons/")
        client._client = Mock()
        initiated = Mock()
        initiated.json.return_value = {
            "session_id": "session-1", "upload_id": "upload-1", "part_size": 8 * 1024 * 1024,
            "urls": ["https://object.example/part-1"],
        }
        response = httpx.Response(400, json={"detail": "Uploaded object verification failed: expected 10 bytes, got 0"})
        completed = Mock()
        completed.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400 Bad Request", request=httpx.Request("POST", "https://example.com/complete"), response=response,
        )
        client._client.post.side_effect = [initiated, completed, Mock()]
        part = Mock()
        part.headers = {"etag": '"etag-1"'}

        with patch("sr_media_manager.api.httpx.put", return_value=part):
            with pytest.raises(Exception, match="Uploaded object verification failed: expected 10 bytes, got 0"):
                client.upload_original("source-1", original)


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

    def _client(self, http_client):
        return MediaManagerClient("https://example.com/projects/TOKEN123/lessons/")
    
    def test_check_video_exists_not_found(self):
        """Test 1: check_video_exists() - not found returns (False, False)."""
        with patch("httpx.Client") as http_client:
            mock_response = Mock()
            mock_response.json.return_value = []
            http_client.return_value.get.return_value = mock_response

            client = self._client(http_client)
            result = client.check_video_exists("test-vid", "Any Title")

        assert result == (False, False)
    
    def test_check_video_exists_found_matching_title(self):
        """Test 2: check_video_exists() - found with matching title returns (True, True)."""
        with patch("httpx.Client") as http_client:
            mock_response = Mock()
            mock_response.json.return_value = [
                {"id": "vid", "title": "Match", "exists": True, "would_overwrite": False}
            ]
            http_client.return_value.get.return_value = mock_response

            client = self._client(http_client)
            result = client.check_video_exists("vid", "Match")

        assert result == (True, True)
    
    def test_check_video_exists_found_different_title(self):
        """Test 3: check_video_exists() - found with different title returns (True, False)."""
        with patch("httpx.Client") as http_client:
            mock_response = Mock()
            mock_response.json.return_value = [
                {"id": "vid", "title": "Different", "exists": True, "would_overwrite": True}
            ]
            http_client.return_value.get.return_value = mock_response

            client = self._client(http_client)
            result = client.check_video_exists("vid", "Expected Title")

        assert result == (True, False)
    
    def test_upload_video_skip_if_exists_exact_match(self):
        """Test 4: upload_video() with skip_if_exists_with_title=True - exact match skips."""
        with patch("httpx.Client") as http_client:
            client = self._client(http_client)
            with patch.object(client, "check_video_exists", return_value=(True, True)):
                result = client.upload_video(
                    "vid",
                    "Same Title",
                    Path("/fake/path.mp4"),
                    skip_if_exists_with_title=True
                )

        http_client.return_value.put.assert_not_called()
        assert result.get("skipped") is True
        assert result.get("uploaded") is False
    
    def test_upload_video_skip_if_exists_will_overwrite(self, tmp_path):
        """Test 5: upload_video() with skip_if_exists_with_title=True - different title triggers overwrite."""
        with patch("httpx.Client") as http_client:
            client = self._client(http_client)

            video_path = tmp_path / "video.mp4"
            video_path.write_bytes(b"fake video")

            with patch.object(client, "check_video_exists", return_value=(True, False)), \
                 patch.object(client, "_upload_presigned", return_value={"ok": True, "overwritten": True, "id": "vid"}) as upload:
                result = client.upload_video(
                    "vid",
                    "New Title",
                    video_path,
                    skip_if_exists_with_title=True
                )

        assert result.get("overwritten") is True
        assert result.get("uploaded") is True
        assert upload.call_args.kwargs["file_type"] == "video"
        assert upload.call_args.kwargs["path"] == video_path

    def test_upload_video_failure_logs_context(self, tmp_path, capsys):
        """Video upload failures should expose enough context to diagnose retry loops."""
        with patch("httpx.Client") as http_client:
            client = self._client(http_client)
            video_path = tmp_path / "video.mp4"
            video_path.write_bytes(b"fake video")
            with patch.object(client, "_upload_presigned", side_effect=TimeoutError("upload timed out")):
                result = client.upload_video("vid", "Title", video_path)

        captured = capsys.readouterr()
        assert result["success"] is False
        assert result["uploaded"] is False
        assert "MEDIA_MANAGER_VIDEO_UPLOAD_FAILED" in captured.err
        assert "id='vid'" in captured.err
        assert "size_bytes=10" in captured.err
        assert "project='lessons'" in captured.err
        assert "error_type=TimeoutError" in captured.err

    def test_check_uploaded_with_title_same_title(self):
        """Test 6: check_uploaded_with_title() helper - video exists, same title."""
        client = Mock()
        client.check_video_exists.return_value = (True, True)

        result = check_uploaded_with_title(client, "vid", "Same Title")

        assert result.get("should_upload") is False
        assert result.get("will_overwrite") is False
        assert result.get("exists") is True

    def test_check_uploaded_with_title_different_title(self):
        """Test 7: check_uploaded_with_title() helper - video exists, different title."""
        client = Mock()
        client.check_video_exists.return_value = (True, False)

        result = check_uploaded_with_title(client, "vid", "Different Title")

        assert result.get("should_upload") is True
        assert result.get("will_overwrite") is True
        assert result.get("exists") is True
