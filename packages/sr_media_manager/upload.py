"""Idempotent upload logic for Media Manager (Phase 3 and Phase 5)."""

from pathlib import Path
from typing import List
from .api import MediaManagerClient


def get_uploaded_audio_ids(client: MediaManagerClient) -> List[str]:
    """Fetch list of already uploaded audio file IDs from server.
    
    Includes trashed files so we don't attempt to re-upload them.
    Returns empty list on error (fail-safe for upload decisions).
    """
    try:
        # Fetch both active and trashed files
        active_files = client.get_audio_files()
        trashed_files = client.get_audio_files(tags='trash')
        all_files = active_files + trashed_files
        return [f.get('id') for f in all_files if f.get('id')]
    except Exception:
        return []


def get_uploaded_video_ids(client: MediaManagerClient) -> List[str]:
    """Fetch list of already uploaded video file IDs from server.
    
    Includes trashed files so we don't attempt to re-upload them.
    Returns empty list on error (fail-safe for upload decisions).
    """
    try:
        # Fetch both active and trashed files
        active_files = client.get_video_files()
        trashed_files = client.get_video_files(tags='trash')
        all_files = active_files + trashed_files
        return [f.get('id') for f in all_files if f.get('id')]
    except Exception:
        return []


def check_uploaded(file_id: str, uploaded_ids: List[str]) -> bool:
    """Check if file_id is in the pre-fetched uploaded list."""
    return file_id in uploaded_ids


def ensure_audio_uploaded(
    client: MediaManagerClient,
    file_id: str,
    title: str,
    audio_path: Path
) -> bool:
    """Upload audio snippet if not already on server (Phase 3).
    
    1. Check if audio file_id exists on server
    2. If not exists: upload audio + title with tags=["todo"]
    3. If exists: no-op (idempotent)
    
    Args:
        client: MediaManagerClient instance
        file_id: Unique identifier (video basename)
        title: Title for the audio
        audio_path: Path to audio snippet file
    
    Returns True if upload succeeded or already exists.
    Returns False on error (logs warning, does not raise).
    """
    try:
        # Check existence
        exists = client.check_exists(file_id, file_type='audio')
        
        if exists:
            return True
        
        # Upload with todo tag for review
        return client.upload_audio(file_id, title, Path(audio_path), tags=['todo'])
    except Exception as e:
        # Log and continue (don't block pipeline)
        print(f"Warning: Audio upload failed for {file_id}: {e}")
        return False


def ensure_video_uploaded(
    client: MediaManagerClient,
    file_id: str,
    title: str,
    video_path: Path
) -> bool:
    """Upload final video if not already on server (Phase 5).
    
    1. Check if video file_id exists on server
    2. If not exists: upload video + title with tags=["FB", "TT"]
    3. If exists: no-op (idempotent)
    
    Args:
        client: MediaManagerClient instance
        file_id: Unique identifier (video basename)
        title: Title for the video
        video_path: Path to final video file
    
    Returns True if upload succeeded or already exists.
    Returns False on error (logs warning, does not raise).
    """
    try:
        # Check existence
        exists = client.check_exists(file_id, file_type='video')
        
        if exists:
            return True
        
        # Upload with FB and TT tags for video platforms
        return client.upload_video(file_id, title, Path(video_path), tags=['FB', 'TT'])
    except Exception as e:
        # Log and continue (don't block pipeline)
        print(f"Warning: Video upload failed for {file_id}: {e}")
        return False
