"""Media Manager HTTP API client."""

import json
import os
from pathlib import Path
from urllib.parse import urljoin, urlparse
import httpx

DEFAULT_TIMEOUT = 30.0


class MediaManagerClient:
    """HTTP client for Media Manager API.
    
    URL format: https://host/token/project/
    Example: https://example.com/TOKEN/PROJECT/
    """
    
    def __init__(self, full_url: str = None):
        """Initialize from full URL or env var MEDIA_MANAGER_URL."""
        full_url = full_url or os.getenv('MEDIA_MANAGER_URL', '')
        if not full_url:
            raise ValueError("MEDIA_MANAGER_URL not set")
        
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
    
    def get_audio_files(self, tags: str = None) -> list[dict]:
        """Fetch audio files from API.
        
        Args:
            tags: Optional tag filter (e.g., "ready", "todo", "trash")
        
        Returns: [{"id": "...", "title": "...", "tags": [...], ...}, ...]
        """
        try:
            url = self._url('/api/files?type=audio')
            if tags:
                url += f'&tags={tags}'
            resp = self._client.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            raise MediaManagerError(f"Failed to fetch audio files: {e}")
    
    def get_video_files(self, tags: str = None) -> list[dict]:
        """Fetch video files from API.
        
        Args:
            tags: Optional tag filter (e.g., "FB", "TT", "trash")
        
        Returns: [{"id": "...", "title": "...", "tags": [...], ...}, ...]
        """
        try:
            url = self._url('/api/files?type=video')
            if tags:
                url += f'&tags={tags}'
            resp = self._client.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            raise MediaManagerError(f"Failed to fetch video files: {e}")
    
    def check_exists(self, file_id: str, file_type: str = 'audio') -> bool:
        """Check if file exists on server by ID and type."""
        try:
            # Check specific type (audio vs video can share same ID)
            files = self.get_audio_files() if file_type == 'audio' else self.get_video_files()
            return any(f.get('id') == file_id for f in files)
        except Exception:
            return False
    
    def upload_audio(self, file_id: str, title: str, audio_path: Path, tags: list = None,
                     progress_callback: callable = None) -> bool:
        """Upload audio snippet with title and tags.
        
        Args:
            file_id: Unique identifier (usually video basename)
            title: Title/caption for the audio
            audio_path: Path to audio file
            tags: List of tags (default: ["todo"])
            progress_callback: Optional callback(uploaded_bytes, total_bytes) for progress updates
        
        Returns True on success.
        """
        tags = tags or ['todo']
        
        try:
            total_size = audio_path.stat().st_size
            
            # Progress-tracking file wrapper
            class ProgressFile:
                def __init__(self, file_path, callback, total):
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
                
                def __enter__(self):
                    return self
                
                def __exit__(self, *args):
                    self._file.close()
            
            with ProgressFile(audio_path, progress_callback, total_size) as pf:
                files = {'file': (f'{file_id}.ogg', pf, 'audio/ogg')}
                data = {
                    'id': file_id,
                    'title': title,
                    'type': 'audio',
                    'tags': json.dumps(tags)
                }
                resp = self._client.post(
                    self._url('/api/files'),
                    data=data,
                    files=files
                )
            return resp.status_code in (200, 201, 409)
        except Exception as e:
            raise MediaManagerError(f"Audio upload failed for {file_id}: {e}")
    
    def upload_video(self, file_id: str, title: str, video_path: Path, tags: list = None, 
                     progress_callback: callable = None) -> bool:
        """Upload final video with title and tags.
        
        Args:
            file_id: Unique identifier (usually video basename)
            title: Title/caption for the video
            video_path: Path to video file
            tags: List of tags (default: ["FB", "TT"])
            progress_callback: Optional callback(uploaded_bytes, total_bytes) for progress updates
        
        Returns True on success.
        """
        tags = tags or ['FB', 'TT']
        
        try:
            mime_type = 'video/mp4'
            if video_path.suffix == '.mov':
                mime_type = 'video/quicktime'
            elif video_path.suffix == '.webm':
                mime_type = 'video/webm'
            
            total_size = video_path.stat().st_size
            
            # Progress-tracking file wrapper
            class ProgressFile:
                def __init__(self, file_path, callback, total):
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
                
                def __enter__(self):
                    return self
                
                def __exit__(self, *args):
                    self._file.close()
            
            with ProgressFile(video_path, progress_callback, total_size) as pf:
                files = {'file': (video_path.name, pf, mime_type)}
                data = {
                    'id': file_id,
                    'title': title,
                    'type': 'video',
                    'tags': json.dumps(tags)
                }
                resp = self._client.post(
                    self._url('/api/files'),
                    data=data,
                    files=files
                )
            return resp.status_code in (200, 201, 409)
        except Exception as e:
            raise MediaManagerError(f"Video upload failed for {file_id}: {e}")
    
    def update_tags(self, file_id: str, tags: list) -> bool:
        """Update file tags."""
        try:
            resp = self._client.put(
                self._url(f'/api/files/{file_id}'),
                json={'tags': tags}
            )
            return resp.status_code == 200
        except Exception as e:
            raise MediaManagerError(f"Tag update failed for {file_id}: {e}")
    
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
