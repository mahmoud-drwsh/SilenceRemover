"""Media Manager API client for the PC pipeline.

The PC pipeline uses this client to:
- Upload the original source recording.
- Send the review snippet for transient title analysis.
"""

from .api import MediaManagerClient, MediaManagerError

__all__ = [
    'MediaManagerClient',
    'MediaManagerError',
]
