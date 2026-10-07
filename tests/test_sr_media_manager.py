"""Tests for sr_media_manager package."""

import json
from pathlib import Path
from unittest.mock import Mock, patch
import httpx
import pytest

from sr_media_manager import MediaManagerClient
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
        assert upload.call_args.kwargs["tags"] == []
        assert upload.call_args.kwargs["media_variant"] == "no-overlay"
        assert upload.call_args.kwargs["visibility"] == "active"
        assert upload.call_args.kwargs["publication_status"] == "published"

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
