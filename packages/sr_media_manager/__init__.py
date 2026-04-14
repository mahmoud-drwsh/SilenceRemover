"""Media Manager API integration - black box package for title sync, audio upload (Phase 4), and video upload (Phase 8).

This package replaces the old sr_mp3_manager and supports the new 8-phase workflow:
- Phase 4: Upload audio snippet for review (tags: ["todo"])
- Phase 8: Upload final video when audio is approved (tags: ["FB", "TT"])
- Two-way sync: Pull edited titles from Media Manager before processing
"""

from .api import MediaManagerClient, MediaManagerError
from .sync import sync_titles_from_api, get_ready_audio_ids
from .upload import (
    ensure_audio_uploaded,
    ensure_video_uploaded,
    get_uploaded_audio_ids,
    get_uploaded_video_ids,
    check_uploaded,
    check_uploaded_with_title,
)

__all__ = [
    # API Client
    'MediaManagerClient',
    'MediaManagerError',
    # Sync (Two-way title sync + ready audio query)
    'sync_titles_from_api',
    'get_ready_audio_ids',
    # Upload (Phase 4 and Phase 8)
    'ensure_audio_uploaded',
    'ensure_video_uploaded',
    'get_uploaded_audio_ids',
    'get_uploaded_video_ids',
    'check_uploaded',
    'check_uploaded_with_title',
]

# Backwards compatibility alias for old import name
Mp3ApiClient = MediaManagerClient
