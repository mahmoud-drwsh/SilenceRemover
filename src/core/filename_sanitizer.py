"""Filename sanitization for title-based output basenames.

This module is now a compatibility shim. The actual implementation has been
moved to packages/sr_filename/ for better testability.
"""

# Re-export from the extracted black box package
from sr_filename import sanitize_filename

__all__ = ["sanitize_filename"]
