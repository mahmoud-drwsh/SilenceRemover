"""Idempotent upload logic for audio snippets."""

from pathlib import Path
from .api import Mp3ApiClient


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
