"""MP3 Manager API integration - black box package for title sync and upload."""

from .api import Mp3ApiClient
from .sync import sync_titles
from .upload import ensure_uploaded

__all__ = ['Mp3ApiClient', 'sync_titles', 'ensure_uploaded']
