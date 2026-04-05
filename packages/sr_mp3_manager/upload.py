"""Idempotent upload logic for audio snippets."""

from pathlib import Path
from typing import List
from .api import Mp3ApiClient


def get_uploaded_file_ids(client: Mp3ApiClient) -> List[str]:
    """Fetch list of already uploaded file IDs from server.
    
    Returns empty list on error (fail-safe for upload decisions).
    """
    try:
        files = client.get_all_files()
        return [f.get('id') for f in files if f.get('id')]
    except Exception:
        return []


def check_uploaded(file_id: str, uploaded_ids: List[str]) -> bool:
    """Check if file_id is in the pre-fetched uploaded list."""
    return file_id in uploaded_ids


def ensure_uploaded(
    client: Mp3ApiClient,
    file_id: str,
    title: str,
    audio_path: Path
) -> bool:
    """Upload snippet if not already on server.
    
    1. Check if file_id exists on server
    2. If not exists: upload audio + title
    3. If exists: no-op (idempotent)
    
    Returns True if upload succeeded or already exists.
    Returns False on error (logs warning, does not raise).
    """
    try:
        # Check existence
        exists = client.check_exists(file_id)
        
        if exists:
            return True
        
        # Upload
        return client.upload(file_id, title, Path(audio_path))
    except Exception as e:
        # Log and continue (don't block pipeline)
        print(f"Warning: MP3 upload failed for {file_id}: {e}")
        return False
