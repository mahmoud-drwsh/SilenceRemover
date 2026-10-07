"""Media Manager HTTP API client."""

import hashlib
import os
import random
import time
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse
import httpx

DEFAULT_TIMEOUT = 30.0
VIDEO_UPLOAD_TIMEOUT = httpx.Timeout(
    connect=30.0,
    write=600.0,
    read=600.0,
    pool=30.0,
)
PART_RETRY_DELAYS_SEC = (0.5, 1.0, 2.0)


class ProgressFile:
    """File wrapper that preserves length detection for multipart uploads."""

    def __init__(self, file_path: Path, callback: callable, total: int):
        self._file = open(file_path, 'rb')
        self._callback = callback
        self._total = total
        self._uploaded = 0

    def read(self, size=-1):
        data = self._file.read(size)
        if data:
            self._uploaded += len(data)
            if self._callback:
                self._callback(self._uploaded, self._total)
        return data

    def fileno(self):
        return self._file.fileno()

    def tell(self):
        return self._file.tell()

    def seek(self, offset, whence=0):
        return self._file.seek(offset, whence)

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class MediaManagerClient:
    """HTTP client for Media Manager API.
    
    URL format: https://host/projects/token/project/
    Example: https://example.com/projects/TOKEN/PROJECT/
    """
    
    def __init__(self, full_url: str = None):
        """Initialize from full URL or env var MEDIA_MANAGER_URL."""
        full_url = full_url or os.getenv('MEDIA_MANAGER_URL', '')
        if not full_url:
            raise ValueError("MEDIA_MANAGER_URL not set")
        
        parsed = urlparse(full_url.rstrip('/'))
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        # Extract token and project from path
        # URL format: https://host/projects/TOKEN/PROJECT/ or https://host/TOKEN/PROJECT/
        path_parts = parsed.path.strip('/').split('/')
        
        # Skip 'projects' prefix if present (new URL format)
        if len(path_parts) >= 3 and path_parts[0] == 'projects':
            self.token = path_parts[1]
            self.project = path_parts[2]
        elif len(path_parts) >= 2:
            # Legacy format without /projects/ prefix
            self.token = path_parts[0]
            self.project = path_parts[1]
        else:
            raise ValueError(f"URL must contain token/project: {full_url}")
        
        self._client = httpx.Client(timeout=DEFAULT_TIMEOUT)
    
    def _url(self, endpoint: str) -> str:
        """Build full API URL with /projects/ prefix."""
        base = f"/projects/{self.token}/{self.project}{endpoint}"
        return urljoin(self.base_url, base)
    
    def get_original_files(self) -> list[dict]:
        """Fetch source recordings uploaded for this project."""
        try:
            resp = self._client.get(self._url('/api/files?type=original'))
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            raise MediaManagerError(f"Failed to fetch original files: {e}")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _is_expired_upload_url(error: Exception) -> bool:
        response = getattr(error, 'response', None)
        return response is not None and response.status_code in (401, 403)

    @staticmethod
    def _is_retryable_upload_error(error: Exception) -> bool:
        if isinstance(error, (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.TimeoutException)):
            return True
        response = getattr(error, 'response', None)
        return response is not None and response.status_code in (408, 429, 500, 502, 503, 504)

    @staticmethod
    def _upload_error_detail(error: Exception) -> str:
        """Keep the API's bounded error detail in pipeline output."""
        response = getattr(error, 'response', None)
        if response is None:
            return str(error)
        try:
            payload = response.json()
            detail = payload.get('detail') if isinstance(payload, dict) else None
            if isinstance(detail, str) and detail:
                return f'{error} ({detail[:500]})'
        except Exception:
            pass
        try:
            body = response.text.strip()
            if body:
                return f'{error} ({body[:500]})'
        except Exception:
            pass
        return str(error)

    def _abort_upload_session(self, session_id: str) -> None:
        try:
            self._client.post(self._url(f'/api/uploads/{quote(session_id, safe="")}/abort')).raise_for_status()
        except Exception:
            pass

    def _upload_presigned(
        self, *, file_id: str, file_type: str, title: str, path: Path, tags: list,
        original_filename: str | None = None,
        progress_callback: callable = None,
    ) -> dict:
        """Transfer one file directly to S3 through the shared upload-session API."""
        size = path.stat().st_size
        mime = {
            '.ogg': 'application/ogg', '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.m4a': 'audio/x-m4a',
            '.mp4': 'video/mp4', '.mov': 'video/quicktime', '.mkv': 'video/x-matroska', '.webm': 'video/webm',
        }.get(path.suffix.lower(), 'video/mp4' if file_type != 'audio' else 'audio/ogg')
        payload = {
            'id': file_id, 'type': file_type, 'title': title, 'tags': tags,
            'mime_type': mime, 'file_size': size, 'checksum_sha256': self._sha256(path),
        }
        if original_filename:
            payload['original_filename'] = original_filename

        for session_restart in range(2):
            session = None
            try:
                response = self._client.post(self._url('/api/uploads/initiate'), json=payload)
                response.raise_for_status()
                session = response.json()
                if session.get('already_uploaded'):
                    return session
                session_id = session['session_id']
                uploaded = 0
                etags = []
                part_size = session.get('part_size')
                urls = session.get('urls') or ([session['upload_url']] if session.get('upload_url') else [])
                if not urls:
                    raise MediaManagerError(f'Upload session {session_id} returned no transfer URL')
                with path.open('rb') as source:
                    for part_number, url in enumerate(urls, start=1):
                        chunk = source.read(part_size or size)
                        if not chunk:
                            raise MediaManagerError(f'Upload {file_id} ended before part {part_number}')
                        last_error = None
                        for attempt, delay in enumerate(PART_RETRY_DELAYS_SEC, start=1):
                            try:
                                result = httpx.put(
                                    url, content=chunk, timeout=VIDEO_UPLOAD_TIMEOUT,
                                    headers={'Content-Type': mime} if not part_size else None,
                                )
                                result.raise_for_status()
                                if part_size:
                                    etag = result.headers.get('etag')
                                    if not etag:
                                        raise MediaManagerError(f'Upload {file_id} part {part_number} is missing an ETag')
                                    etags.append({'part_number': part_number, 'etag': etag})
                                uploaded += len(chunk)
                                if progress_callback:
                                    progress_callback(uploaded, size)
                                break
                            except Exception as exc:
                                last_error = exc
                                if self._is_expired_upload_url(exc):
                                    raise
                                if not self._is_retryable_upload_error(exc) or attempt == len(PART_RETRY_DELAYS_SEC):
                                    raise MediaManagerError(
                                        f'Upload {file_id} part {part_number} failed after {attempt} attempts: {exc}'
                                    ) from exc
                                time.sleep(delay * random.uniform(0.8, 1.2))
                        else:
                            raise MediaManagerError(f'Upload {file_id} part {part_number} failed: {last_error}')
                complete = self._client.post(
                    self._url(f'/api/uploads/{quote(session_id, safe="")}/complete'),
                    json={'parts': etags} if part_size else {},
                )
                complete.raise_for_status()
                return complete.json()
            except Exception as exc:
                if session:
                    self._abort_upload_session(session['session_id'])
                if self._is_expired_upload_url(exc) and session_restart == 0:
                    continue
                raise MediaManagerError(
                    f'{file_type} upload failed for {file_id}: {self._upload_error_detail(exc)}'
                ) from exc
        raise MediaManagerError(f'{file_type} upload failed for {file_id}: presigned URL expired twice')

    def upload_original(self, source_id: str, original_path: Path, progress_callback: callable = None) -> bool:
        """Upload an original through the shared presigned session API."""
        self._upload_presigned(
            file_id=source_id, file_type='original', title=original_path.name, path=original_path,
            tags=[], original_filename=original_path.name, progress_callback=progress_callback,
        )
        return True

    def analyze_ogg_snippet(self, snippet_path: Path) -> tuple[str, str]:
        """Return a transient server-generated ``(transcript, title)`` for an OGG snippet.

        The snippet is sent only in this authenticated multipart request. It is
        neither uploaded through the Media Manager file API nor retained by the
        client helper after the request finishes.
        """
        path = Path(snippet_path)
        if path.suffix.lower() != ".ogg":
            raise MediaManagerError(f"Snippet analysis requires an OGG file, got {path.name}")
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise MediaManagerError(f"Could not read OGG snippet {path}: {exc}") from exc
        if size <= 0 or size > 4 * 1024 * 1024:
            raise MediaManagerError("OGG snippet must be between 1 byte and 4 MiB")
        try:
            with path.open("rb") as stream:
                response = self._client.post(
                    self._url("/api/snippet-analysis"),
                    files={"snippet": (path.name, stream, "audio/ogg")},
                    timeout=VIDEO_UPLOAD_TIMEOUT,
                )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise MediaManagerError(
                f"Server-side snippet analysis failed: {self._upload_error_detail(exc)}"
            ) from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise MediaManagerError("Server-side snippet analysis returned an invalid response")
        transcript = payload.get("transcript")
        title = payload.get("title")
        if not isinstance(transcript, str) or not transcript.strip():
            raise MediaManagerError("Server-side snippet analysis returned an empty transcript")
        if not isinstance(title, str) or not title.strip() or "\n" in title or "\r" in title:
            raise MediaManagerError("Server-side snippet analysis returned an invalid title")
        return transcript.strip(), title.strip()

    def update_tags(self, file_id: str, tags: list, file_type: str = 'audio') -> bool:
        """Update file tags.
        
        Args:
            file_id: File identifier
            tags: New list of tags
            file_type: 'audio' or 'video' (required by API)
        """
        try:
            resp = self._client.put(
                self._url(f'/api/files/{file_id}?type={file_type}'),
                json={'tags': tags}
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            raise MediaManagerError(f"Tag update failed for {file_id}: {e}") from e

    def delete_file(self, file_id: str, file_type: str = 'video') -> bool:
        """Delete a file (trash first, then permanently).
        
        Args:
            file_id: File identifier
            file_type: 'audio' or 'video' (default: 'video')
        
        Returns: True on success (including if file already gone)
        """
        try:
            self.update_tags(file_id, ['trash'], file_type=file_type)
        except MediaManagerError as e:
            # A worker may finish its cleanup before this check reaches it.
            # Preserve the client's idempotent delete contract for that case,
            # while surfacing every other non-2xx response to callers.
            if isinstance(e.__cause__, httpx.HTTPStatusError) and e.__cause__.response.status_code == 404:
                return True
            raise
        try:
            response = self._client.delete(self._url(f'/api/files/{file_id}?type={file_type}'))
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return True
            if 'Only trashed files can be deleted' in str(e):
                raise MediaManagerError(f"Cannot delete {file_id}: file must be trashed first") from e
            raise MediaManagerError(f"Delete failed for {file_id}: {e}") from e
        except Exception as e:
            if 'Only trashed files can be deleted' in str(e):
                raise MediaManagerError(f"Cannot delete {file_id}: file must be trashed first")
            raise MediaManagerError(f"Delete failed for {file_id}: {e}") from e
    
    def close(self):
        """Close HTTP client."""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()


class MediaManagerError(Exception):
    """API error wrapper."""
    pass
