"""Media Manager API integration - black box package for title sync and media upload.

This package replaces the old sr_mp3_manager and supports the Phase-0-to-13 workflow:
- Phase 4: Upload original source recording
- Phase 5: Upload audio snippet for review (tags: ["todo"])
- Phases 11-12: Upload overlaid and no-overlay videos with tags ["pending"]
- Phase 13: Promote the overlaid video to ["FB", "TT"] when audio approved
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
    # Upload helpers
    'ensure_audio_uploaded',
    'ensure_video_uploaded',
    'get_uploaded_audio_ids',
    'get_uploaded_video_ids',
    'check_uploaded',
    'check_uploaded_with_title',
]

# Backwards compatibility alias for old import name
Mp3ApiClient = MediaManagerClient
