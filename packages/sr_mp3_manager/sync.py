"""Title synchronization logic: API → local .txt files."""

from pathlib import Path
from .api import Mp3ApiClient


def sync_titles(
    client: Mp3ApiClient,
    titles_dir: Path,
    completed_dir: Path
) -> list[str]:
    """Sync titles from API to local .txt files.
    
    For each file returned by API:
    - Compare API title to local title.txt (if exists)
    - If different: overwrite .txt with API title, delete completed/ entry
    - If same: do nothing
    
    Missing API entries are ignored (no action taken).
    
    Returns: list of file IDs that were updated (for logging).
    """
    titles_dir = Path(titles_dir)
    completed_dir = Path(completed_dir)
    titles_dir.mkdir(parents=True, exist_ok=True)
    completed_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        files = client.get_all_files()
    except Exception:
        # Fail-safe: any error, return empty (no changes)
        return []
    
    updated_ids = []
    
    for file_info in files:
        file_id = file_info.get('id')
        api_title = (file_info.get('title') or '').strip()
        
        if not file_id:
            continue
        
        # Read current local title
        title_path = titles_dir / f"{file_id}.txt"
        if title_path.exists():
            current_title = title_path.read_text(encoding='utf-8').strip()
        else:
            current_title = ''
        
        # Compare and update if different
        if api_title != current_title:
            title_path.write_text(api_title, encoding='utf-8')
            
            # Delete from completed to trigger Phase 4 re-encode
            completed_path = completed_dir / f"{file_id}.txt"
            if completed_path.exists():
                completed_path.unlink()
            
            updated_ids.append(file_id)
    
    return updated_ids
