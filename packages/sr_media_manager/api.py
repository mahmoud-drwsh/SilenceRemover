"""Media Manager HTTP API client."""

import json
import os
from pathlib import Path
from urllib.parse import urljoin, urlparse
import httpx

DEFAULT_TIMEOUT = 30.0


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
    
    def get_audio_files(self, tags: str = None, include_trash: bool = False) -> list[dict]:
        """Fetch audio files from API.
        
        Args:
            tags: Optional tag filter (e.g., "ready", "todo", "trash")
            include_trash: If True, include trashed files even when no tag filter (default: False)
        
        Returns: [{"id": "...", "title": "...", "tags": [...], ...}, ...]
        """
        try:
            url = self._url('/api/files?type=audio')
            if tags:
                url += f'&tags={tags}'
            if include_trash:
                url += '&include_trash=true'
            resp = self._client.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            raise MediaManagerError(f"Failed to fetch audio files: {e}")
    
    def get_video_files(self, tags: str = None, include_trash: bool = False) -> list[dict]:
        """Fetch video files from API.
        
        Args:
            tags: Optional tag filter (e.g., "FB", "TT", "trash")
            include_trash: If True, include trashed files even when no tag filter (default: False)
        
        Returns: [{"id": "...", "title": "...", "tags": [...], ...}, ...]
        """
        try:
            url = self._url('/api/files?type=video')
            if tags:
                url += f'&tags={tags}'
            if include_trash:
                url += '&include_trash=true'
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

    def check_audio_exists(self, file_id: str) -> tuple[bool, str | None]:
        """Check if audio file exists and get its title.

        Args:
            file_id: Audio file identifier

        Returns:
            tuple(exists, title)
            - (False, None): Audio not on server
            - (True, title): Audio exists with title
        """
        try:
            from urllib.parse import quote
            url = self._url(f'/api/files?type=audio&check_id={quote(file_id, safe="")}')
            resp = self._client.get(url)
            resp.raise_for_status()
            files = resp.json()

            if files and len(files) > 0:
                file_info = files[0]
                exists = file_info.get('exists', True)  # Default True if returned
                title = file_info.get('title', '')
                return (exists, title if exists else None)

            return (False, None)
        except Exception:
            # Fail open - assume doesn't exist
            return (False, None)

    def get_ready_audio_with_title(self, file_id: str) -> tuple[bool, str | None]:
        """Check if audio is marked as ready and get its approved title.

        Args:
            file_id: Audio file identifier

        Returns:
            tuple(is_ready, approved_title)
            - (False, None): Audio not ready or not found
            - (True, title): Audio is ready with approved title
        """
        try:
            from urllib.parse import quote
            url = self._url(f'/api/files?type=audio&tags=ready&check_id={quote(file_id, safe="")}')
            resp = self._client.get(url)
            resp.raise_for_status()
            files = resp.json()

            if files and len(files) > 0:
                file_info = files[0]
                exists = file_info.get('exists', True)
                title = file_info.get('title', '')
                return (exists, title if exists else None)

            return (False, None)
        except Exception:
            # Fail-safe: not ready
            return (False, None)

    def check_video_exists(self, file_id: str, title: str) -> tuple[bool, bool]:
        """Check if video exists and if title matches.

        Args:
            file_id: Video identifier
            title: Expected title to compare

        Returns:
            tuple(exists, title_matches)
            - (False, False): Video not on server
            - (True, True): Video exists with same title
            - (True, False): Video exists but title differs (will overwrite)
        """
        try:
            # Query with check_id and check_title for pre-flight endpoint
            from urllib.parse import quote
            encoded_title = quote(title, safe='')
            url = self._url(f'/api/files?type=video&check_id={file_id}&check_title={encoded_title}')
            resp = self._client.get(url)
            resp.raise_for_status()
            files = resp.json()

            if files and len(files) > 0:
                # Check if server indicated a match with same title
                file_info = files[0]
                exists = file_info.get('exists', False)
                would_overwrite = file_info.get('would_overwrite')
                
                if exists and would_overwrite is False:
                    # exists=True and would_overwrite=False means same title
                    return (True, True)
                if exists and would_overwrite is True:
                    # exists=True and would_overwrite=True means different title
                    return (True, False)
                # Fall through to check_exists for backward compatibility

            # No match with this title - check if file exists at all
            exists = self.check_exists(file_id, file_type='video')
            return (exists, False)

        except Exception:
            # Fail open - assume doesn't exist to allow upload attempt
            return (False, False)

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
            if resp.status_code not in (200, 201, 409):
                # Include response body for debugging
                try:
                    body = resp.text[:200]  # First 200 chars
                except Exception:
                    body = "<could not read response>"
                raise MediaManagerError(f"Server returned {resp.status_code}: {body}")
            return True
        except Exception as e:
            if isinstance(e, MediaManagerError):
                raise
            raise MediaManagerError(f"Audio upload failed for {file_id}: {e}")
    
    def upload_video(
        self,
        file_id: str,
        title: str,
        video_path: Path,
        tags: list = None,
        progress_callback: callable = None,
        skip_if_exists_with_title: bool = False
    ) -> dict:
        """Upload final video with title and tags.

        Args:
            file_id: Unique identifier (usually video basename)
            title: Title/caption for the video
            video_path: Path to video file
            tags: List of tags (default: ["FB", "TT"])
            progress_callback: Optional callback(uploaded_bytes, total_bytes) for progress updates
            skip_if_exists_with_title: If True, check existence+title before upload to avoid unnecessary transfers

        Returns:
            {
                'success': bool,
                'uploaded': bool,      # Bytes were actually transferred
                'skipped': bool,       # Existed with same title, not uploaded
                'overwritten': bool,   # Server replaced existing file
                'error': str or None
            }
        """
        tags = tags or ['FB', 'TT']

        # Pre-flight check if requested
        if skip_if_exists_with_title:
            exists, title_matches = self.check_video_exists(file_id, title)
            if exists and title_matches:
                # Silent skip - no terminal clutter
                return {
                    'success': True,
                    'uploaded': False,
                    'skipped': True,
                    'overwritten': False,
                    'error': None
                }
            # If exists but title differs, continue to upload (overwrite)

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
                resp.raise_for_status()

                response_json = resp.json()
                overwritten = response_json.get('overwritten', False) if isinstance(response_json, dict) else False

                if overwritten:
                    print(f"[Media Manager] Video {file_id} overwritten on server")

                return {
                    'success': True,
                    'uploaded': True,
                    'skipped': False,
                    'overwritten': overwritten,
                    'error': None
                }
        except Exception as e:
            return {
                'success': False,
                'uploaded': False,
                'skipped': False,
                'overwritten': False,
                'error': str(e)
            }
    
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
            return resp.status_code == 200
        except Exception as e:
            raise MediaManagerError(f"Tag update failed for {file_id}: {e}")

    def delete_file(self, file_id: str, file_type: str = 'video') -> bool:
        """Delete a file (trash first, then permanently).
        
        Args:
            file_id: File identifier
            file_type: 'audio' or 'video' (default: 'video')
        
        Returns: True on success (including if file already gone)
        """
        self.update_tags(file_id, ['trash'], file_type=file_type)
        try:
            self._client.delete(self._url(f'/api/files/{file_id}?type={file_type}'))
            return True
        except Exception as e:
            if '404' in str(e):
                return True
            if 'Only trashed files can be deleted' in str(e):
                raise MediaManagerError(f"Cannot delete {file_id}: file must be trashed first")
            raise MediaManagerError(f"Delete failed for {file_id}: {e}")
    
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
