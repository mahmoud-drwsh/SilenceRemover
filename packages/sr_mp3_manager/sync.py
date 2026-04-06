"""Title synchronization logic: API → local .txt files."""

import time
from pathlib import Path
from sr_filename import sanitize_filename
from .api import Mp3ApiClient


# Retry configuration for AV interference on Windows
_MAX_RETRIES = 5
_RETRY_DELAY_SEC = 0.5


def _write_text_with_retry(path: Path, text: str) -> None:
    """Write text file with retry for AV locking."""
    for attempt in range(_MAX_RETRIES):
        try:
            path.write_text(text, encoding='utf-8')
            return
        except PermissionError:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY_SEC)
            else:
                raise


def _unlink_with_retry(path: Path) -> None:
    """Delete file with retry for AV locking."""
    for attempt in range(_MAX_RETRIES):
        try:
            path.unlink()
            return
        except PermissionError:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY_SEC)
            else:
                raise
        except FileNotFoundError:
            return


def _read_text_with_retry(path: Path) -> str:
    """Read text file with retry for AV locking."""
    for attempt in range(_MAX_RETRIES):
        try:
            return path.read_text(encoding='utf-8')
        except PermissionError:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY_SEC)
            else:
                raise


def sync_titles(
    client: Mp3ApiClient,
    titles_dir: Path,
    completed_dir: Path,
    output_dir: Path,
) -> list[tuple[str, str, str]]:
    """Sync titles from API to local .txt files.
    
    For each file returned by API:
    - Compare API title to local title.txt (if exists)
    - If different: 
        - Overwrite .txt with API title
        - Delete completed/ entry to trigger re-encode
        - Delete old output MP4 (from previous title) if exists
    - If same: do nothing
    
    Missing API entries are ignored (no action taken).
    
    Returns: list of (file_id, old_title, new_title) tuples for logging.
    """
    titles_dir = Path(titles_dir)
    completed_dir = Path(completed_dir)
    output_dir = Path(output_dir)
    titles_dir.mkdir(parents=True, exist_ok=True)
    completed_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        files = client.get_all_files()
    except Exception:
        # Fail-safe: any error, return empty (no changes)
        return []
    
    updated: list[tuple[str, str, str]] = []
    
    for file_info in files:
        file_id = file_info.get('id')
        api_title = (file_info.get('title') or '').strip()
        
        if not file_id:
            continue
        
        # Read current local title
        title_path = titles_dir / f"{file_id}.txt"
        if title_path.exists():
            current_title = _read_text_with_retry(title_path).strip()
        else:
            current_title = ''
        
        # Compare and update if different
        if api_title != current_title:
            # Write new title with retry (AV may lock)
            _write_text_with_retry(title_path, api_title)
            
            # Delete from completed to trigger Phase 4 re-encode
            completed_path = completed_dir / f"{file_id}.txt"
            if completed_path.exists():
                _unlink_with_retry(completed_path)
            
            # Delete old output MP4 if it exists (based on old title)
            if current_title:
                old_basename = sanitize_filename(current_title)
                old_output_path = output_dir / f"{old_basename}.mp4"
                if old_output_path.exists():
                    _unlink_with_retry(old_output_path)
            
            updated.append((file_id, current_title, api_title))
    
    return updated
