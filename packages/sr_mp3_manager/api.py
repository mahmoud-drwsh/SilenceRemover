"""MP3 Manager HTTP API client."""

import os
from pathlib import Path
from urllib.parse import urljoin, urlparse
import httpx

DEFAULT_TIMEOUT = 30.0


class Mp3ApiClient:
    """Minimal HTTP client for MP3 Manager API.
    
    URL format: https://host/token/project/
    Example: https://example.com/TOKEN/PROJECT/
    """
    
    def __init__(self, full_url: str = None):
        """Initialize from full URL or env var MP3_MANAGER_URL."""
        full_url = full_url or os.getenv('MP3_MANAGER_URL', '')
        if not full_url:
            raise ValueError("MP3_MANAGER_URL not set")
        
        parsed = urlparse(full_url.rstrip('/'))
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        # Extract token and project from path
        path_parts = parsed.path.strip('/').split('/')
        if len(path_parts) < 2:
            raise ValueError(f"URL must contain token/project: {full_url}")
        
        self.token = path_parts[0]
        self.project = path_parts[1]
        
        self._client = httpx.Client(timeout=DEFAULT_TIMEOUT)
    
    def _url(self, endpoint: str) -> str:
        """Build full API URL."""
        base = f"/{self.token}/{self.project}{endpoint}"
        return urljoin(self.base_url, base)
    
    def get_all_files(self) -> list[dict]:
        """Fetch all files with titles from API.
        
        Returns: [{"id": "video.mp4", "title": "...", "ready": bool}, ...]
        """
        try:
            resp = self._client.get(self._url('/api/files'))
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            # Fail-safe: return empty list, caller logs
            raise Mp3ApiError(f"Failed to fetch files: {e}")
    
    def check_exists(self, file_id: str) -> bool:
        """Check if file exists on server by ID."""
        try:
            resp = self._client.head(self._url(f'/api/files/{file_id}'))
            return resp.status_code == 200
        except Exception:
            return False
    
    def upload(self, file_id: str, title: str, audio_path: Path) -> bool:
        """Upload audio snippet with title.
        
        Returns True on success, False on failure.
        Idempotent: safe to call if already exists.
        """
        try:
            with open(audio_path, 'rb') as f:
                files = {'audio': (f'{file_id}.ogg', f, 'audio/ogg')}
                data = {'id': file_id, 'title': title}
                resp = self._client.post(
                    self._url('/api/upload'),
                    data=data,
                    files=files
                )
            # 200 = created or updated, 409 = already exists (both OK)
            return resp.status_code in (200, 201, 409)
        except Exception as e:
            raise Mp3ApiError(f"Upload failed for {file_id}: {e}")
    
    def close(self):
        """Close HTTP client."""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()


class Mp3ApiError(Exception):
    """API error wrapper."""
    pass
