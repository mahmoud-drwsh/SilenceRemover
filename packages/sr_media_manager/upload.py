"""Idempotent upload logic for Media Manager (Phase 3 and Phase 5)."""

from pathlib import Path
from typing import List
from .api import MediaManagerClient


def check_uploaded_with_title(
    client: MediaManagerClient,
    file_id: str,
    title: str,
    file_type: str = 'video'
) -> dict:
    """Pre-flight check combining existence + title comparison.

    Returns:
        {
            'exists': bool,
            'title_matches': bool,
            'should_upload': bool,      # True if upload needed
            'will_overwrite': bool,     # True if existing will be replaced
        }
    """
    result = {
        'exists': False,
        'title_matches': False,
        'should_upload': True,
        'will_overwrite': False
    }

    try:
        if file_type == 'video':
            exists, matches = client.check_video_exists(file_id, title)
            result.update({
                'exists': exists,
                'title_matches': matches,
                'should_upload': not (exists and matches),
                'will_overwrite': exists and not matches
            })
        else:
            # Audio - no title comparison in current API
            result['exists'] = client.check_exists(file_id, 'audio')
            result['should_upload'] = not result['exists']

        return result
    except Exception:
        return result  # Fail open (should_upload=True)


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
    video_path: Path,
    optimize: bool = False
) -> dict:
    """Upload final video with optional pre-flight optimization.

    Args:
        client: MediaManagerClient instance
        file_id: Unique identifier (video basename)
        title: Title for the video
        video_path: Path to final video file
        optimize: If True, check existence+title before upload to avoid
                 unnecessary transfers. Adds one API round-trip.

    Returns:
        {
            'success': bool,           # Upload succeeded or skipped appropriately
            'uploaded': bool,          # Bytes were actually transferred
            'skipped': bool,           # Existed with same title, not uploaded
            'overwritten': bool,       # Server replaced existing file
            'error': str or None
        }
    """
    try:
        # Pre-flight check if requested
        if optimize:
            check = check_uploaded_with_title(client, file_id, title, 'video')
            if not check['should_upload']:
                # Silent skip - no terminal clutter
                return {
                    'success': True,
                    'uploaded': False,
                    'skipped': True,
                    'overwritten': False,
                    'error': None
                }
            # If will_overwrite, continue to upload silently

        # Upload with skip_if_exists_with_title=optimize to leverage server's check
        result = client.upload_video(
            file_id,
            title,
            Path(video_path),
            tags=['FB', 'TT'],
            skip_if_exists_with_title=optimize
        )

        return result
    except Exception as e:
        # Log and continue (don't block pipeline)
        error_msg = str(e)
        print(f"Warning: Video upload failed for {file_id}: {error_msg}")
        return {
            'success': False,
            'uploaded': False,
            'skipped': False,
            'overwritten': False,
            'error': error_msg
        }
