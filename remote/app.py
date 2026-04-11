#!/usr/bin/env python3
"""
Media Manager Backend
FastAPI service for audio/video file management with tag-based organization.

Environment variables:
    MEDIA_TOKEN - Authentication token (required)
    DATA_DIR - Where to store db and files (default: /var/lib/media-manager)
    PROJECT_NAME - Project identifier (default: 'default')
"""

import os
import json
import sqlite3
import magic
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager
from typing import List, Optional, Literal

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import aiofiles
from pydantic import BaseModel

# Config
TOKEN = os.environ.get('MEDIA_TOKEN')
DATA_DIR = Path(os.environ.get('DATA_DIR', '/var/lib/media-manager'))
STORAGE_DIR = DATA_DIR / 'storage'
DB_PATH = DATA_DIR / 'database.db'
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
PROJECT_NAME = os.environ.get('PROJECT_NAME', 'default')

# Audio MIME types
AUDIO_MIME = {
    'audio/mpeg', 'audio/mp3', 'audio/mp4', 'audio/wav', 'audio/x-wav',
    'audio/ogg', 'audio/flac', 'audio/x-flac', 'audio/aac', 'audio/x-m4a',
}

# Video MIME types
VIDEO_MIME = {
    'video/mp4', 'video/x-m4v', 'video/webm', 'video/ogg',
    'video/quicktime', 'video/x-msvideo', 'video/x-matroska'
}

ALLOWED_MIME = AUDIO_MIME | VIDEO_MIME

# File extensions by MIME type
MIME_TO_EXT = {
    'audio/mpeg': '.mp3',
    'audio/mp3': '.mp3',
    'audio/mp4': '.m4a',
    'audio/wav': '.wav',
    'audio/x-wav': '.wav',
    'audio/ogg': '.ogg',
    'audio/flac': '.flac',
    'audio/x-flac': '.flac',
    'audio/aac': '.aac',
    'audio/x-m4a': '.m4a',
    'video/mp4': '.mp4',
    'video/x-m4v': '.m4v',
    'video/webm': '.webm',
    'video/ogg': '.ogv',
    'video/quicktime': '.mov',
    'video/x-msvideo': '.avi',
    'video/x-matroska': '.mkv',
}

# Audio tags (fixed)
AUDIO_TAGS = {'todo', 'ready', 'all', 'trash', 'delivered'}


# Pydantic models
class FileResponseModel(BaseModel):
    id: str
    project: str
    type: Literal['audio', 'video']
    title: Optional[str]
    tags: List[str]
    duration: int
    file_size: int
    mime_type: str
    created_at: str


class UpdateFileRequest(BaseModel):
    tags: List[str]
    title: Optional[str] = None


class UploadResponse(BaseModel):
    ok: bool
    id: str
    type: str
    overwritten: bool = False


def init_db():
    """Initialize database with tag-based schema.
    
    Note: For migrating from old Flask schema (ready/trashed columns),
    use scripts/migrate-db.py separately before starting the service.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (STORAGE_DIR / 'audio').mkdir(parents=True, exist_ok=True)
    (STORAGE_DIR / 'video').mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Create project subdirectories for existing projects (dual-path support)
    try:
        projects = conn.execute('SELECT DISTINCT project FROM files').fetchall()
        for row in projects:
            (STORAGE_DIR / 'audio' / row['project']).mkdir(parents=True, exist_ok=True)
            (STORAGE_DIR / 'video' / row['project']).mkdir(parents=True, exist_ok=True)
    except sqlite3.OperationalError:
        # Table doesn't exist yet (first run), will be created below
        pass
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS files (
            id TEXT NOT NULL,
            project TEXT NOT NULL,
            type TEXT NOT NULL,
            title TEXT,
            tags TEXT NOT NULL DEFAULT '[]',
            duration INTEGER DEFAULT 0,
            file_size INTEGER DEFAULT 0,
            mime_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id, type, project)
        );
        CREATE INDEX IF NOT EXISTS idx_project ON files(project);
        CREATE INDEX IF NOT EXISTS idx_type ON files(type);
    ''')
    conn.commit()
    conn.close()


def get_db():
    """Get database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_mime_type(file_path: Path) -> str:
    """Get MIME type of file."""
    return magic.from_file(str(file_path), mime=True)


def get_file_extension(mime_type: str) -> str:
    """Get file extension for MIME type."""
    return MIME_TO_EXT.get(mime_type, '.bin')


def sanitize_filename(name: str) -> str:
    r"""Sanitize a string for use as a filesystem filename.
    
    Removes reserved filesystem characters (/ \ : * ? " < > |) and control chars.
    Falls back to empty string if result is empty (caller should handle fallback).
    """
    if not name:
        return ""
    # Remove control chars and reserved filesystem characters
    reserved = '/\\:*?"<>|'
    cleaned = "".join(c for c in name if c not in "\0\n\r\t" and c not in reserved)
    cleaned = " ".join(cleaned.split()).strip()  # Collapse multiple spaces
    return cleaned[:200]  # Limit length to avoid filesystem limits


def sanitize_file_id(file_id: str) -> str:
    r"""Sanitize file ID to prevent path traversal attacks.
    
    Removes path traversal characters (.., /, \, null bytes) from file IDs.
    Limits length to prevent filesystem issues.
    
    Args:
        file_id: The file ID to sanitize
        
    Returns:
        Sanitized file ID safe for filesystem operations
    """
    if not file_id:
        return ""
    # Remove path traversal and dangerous characters
    cleaned = file_id.replace('..', '').replace('/', '').replace('\\', '').replace('\0', '')
    # Remove other potentially dangerous characters
    cleaned = cleaned.replace(':', '').replace('*', '').replace('?', '').replace('"', '')
    cleaned = cleaned.replace('<', '').replace('>', '').replace('|', '')
    return cleaned[:200]  # Limit length


def resolve_file_path(file_type: str, project: str, file_id: str, ext: str) -> Path:
    """
    Resolve file path with dual-path compatibility.
    
    NEW structure: storage/{type}/{project}/{id}.{ext}
    OLD structure: storage/{type}/{id}.{ext} (legacy, pre-migration)
    
    Returns new path if it exists, otherwise falls back to old path.
    Always returns new path for new uploads (doesn't check existence).
    """
    new_path = STORAGE_DIR / file_type / project / f"{file_id}{ext}"
    old_path = STORAGE_DIR / file_type / f"{file_id}{ext}"
    
    # Prefer new path if it exists, fall back to old path for legacy files
    if new_path.exists():
        return new_path
    if old_path.exists():
        return old_path
    # Neither exists - return new path (for upload/create operations)
    return new_path


def parse_tags(tags_param: Optional[str]) -> Optional[List[str]]:
    """Parse comma-separated tags into list."""
    if not tags_param:
        return None
    return [t.strip() for t in tags_param.split(',') if t.strip()]


def validate_audio_tags(tags: List[str]) -> List[str]:
    """Validate that audio tags are from the fixed set."""
    invalid = set(tags) - AUDIO_TAGS
    if invalid:
        raise HTTPException(400, f"Invalid audio tags: {invalid}. Allowed: {AUDIO_TAGS}")
    return tags


def normalize_title(title: Optional[str]) -> str:
    """Normalize title for comparison: strip whitespace, treat None as empty string."""
    if title is None:
        return ""
    return title.strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    init_db()
    if not TOKEN:
        raise RuntimeError("MEDIA_TOKEN environment variable not set")
    yield


app = FastAPI(title="Media Manager", lifespan=lifespan)


def verify_token(token: str):
    """Verify the provided token matches expected."""
    if token != TOKEN:
        raise HTTPException(401, "Invalid token")


# API Endpoints
@app.get("/{token}/{project}/api/files", response_model=List[FileResponseModel])
def list_files(
    token: str,
    project: str,
    type: Optional[Literal['audio', 'video']] = Query(None, description="Filter by type"),
    tags: Optional[str] = Query(None, description="Comma-separated tags (AND logic)"),
    sort: Optional[Literal['asc', 'desc']] = Query('asc', description="Sort order: asc or desc"),
    check_id: Optional[str] = Query(None, description="Pre-flight: check specific ID for existence"),
    check_title: Optional[str] = Query(None, description="Pre-flight: check if title matches (requires check_id)")
):
    verify_token(token)
    """
    List files with optional filtering.

    - No tags: Returns all files except those with 'trash' tag
    - tags=trash: Returns only trashed files
    - tags=FB,TT: Returns files with BOTH tags (AND logic)
    - sort=asc|desc: Sort by ID ascending (default) or descending
    - check_id: Pre-flight check for specific ID (returns single-item list if exists)
    - check_id + check_title: Returns match info indicating if overwrite would occur
    """
    conn = get_db()
    
    # Pre-flight check mode: check_id provided
    if check_id:
        # Sanitize check_id
        check_id = sanitize_file_id(check_id)
        if not check_id:
            conn.close()
            raise HTTPException(400, "Invalid check_id")
        
        # Query specific ID+project+type (type is required for pre-flight)
        if not type:
            conn.close()
            raise HTTPException(400, "Type parameter is required when using check_id")
        
        row = conn.execute(
            '''SELECT id, project, type, title, tags, duration, file_size, mime_type, created_at 
               FROM files WHERE id = ? AND project = ? AND type = ?''',
            (check_id, project, type)
        ).fetchone()
        conn.close()
        
        if row:
            existing_title = normalize_title(row['title'])
            
            # If check_title provided, determine match/overwrite status
            if check_title is not None:
                check_title_normalized = normalize_title(check_title)
                would_overwrite = (existing_title != check_title_normalized)
                
                # Return with match info
                response = FileResponseModel(
                    id=row['id'],
                    project=row['project'],
                    type=row['type'],
                    title=row['title'],
                    tags=json.loads(row['tags']),
                    duration=row['duration'],
                    file_size=row['file_size'],
                    mime_type=row['mime_type'],
                    created_at=row['created_at']
                )
                # Add extra fields via JSONResponse
                return JSONResponse(content=[{
                    **response.model_dump(),
                    "exists": True,
                    "would_overwrite": would_overwrite,
                    "existing_title": existing_title,
                    "provided_title": check_title_normalized
                }])
            
            # No check_title, just return the file info
            return [FileResponseModel(
                id=row['id'],
                project=row['project'],
                type=row['type'],
                title=row['title'],
                tags=json.loads(row['tags']),
                duration=row['duration'],
                file_size=row['file_size'],
                mime_type=row['mime_type'],
                created_at=row['created_at']
            )]
        else:
            # ID not found - return empty list with not_found info
            return JSONResponse(content=[{
                "exists": False,
                "id": check_id,
                "type": type,
                "project": project
            }])
    
    # Normal list mode (no check_id)
    tag_list = parse_tags(tags)

    # Build query
    conditions = ["project = ?"]
    params = [project]

    if type:
        conditions.append("type = ?")
        params.append(type)

    # Tag filtering logic
    if tag_list:
        if 'trash' in tag_list:
            # Specifically looking for trash - show only trash tag
            conditions.append("tags LIKE ?")
            params.append('%"trash"%')
            # Add other tags if any
            for tag in tag_list:
                if tag != 'trash':
                    conditions.append("tags LIKE ?")
                    params.append(f'%"{tag}"%')
        else:
            # Looking for specific tags - files must have ALL specified tags
            for tag in tag_list:
                conditions.append("tags LIKE ?")
                params.append(f'%"{tag}"%')
    else:
        # No tags specified (ALL tab) - exclude trash only, include empty tags
        conditions.append("tags NOT LIKE ?")
        params.append('%"trash"%')

    where_clause = " AND ".join(conditions)
    # Validate sort direction to prevent SQL injection
    sort_direction = 'ASC' if sort == 'asc' else 'DESC'

    rows = conn.execute(
        f'''
        SELECT id, project, type, title, tags, duration, file_size, mime_type, created_at
        FROM files
        WHERE {where_clause}
        ORDER BY id {sort_direction}
        ''',
        params
    ).fetchall()
    conn.close()

    return [
        FileResponseModel(
            id=row['id'],
            project=row['project'],
            type=row['type'],
            title=row['title'],
            tags=json.loads(row['tags']),
            duration=row['duration'],
            file_size=row['file_size'],
            mime_type=row['mime_type'],
            created_at=row['created_at']
        )
        for row in rows
    ]


@app.post("/{token}/{project}/api/files", response_model=UploadResponse)
async def upload_file(
    token: str,
    project: str,
    id: str = Form(..., description="File ID (usually video basename)"),
    title: str = Form('', description="Title/caption"),
    type: Literal['audio', 'video'] = Form(..., description="File type"),
    tags: str = Form('[]', description="JSON array of tags"),
    file: UploadFile = File(...)
):
    verify_token(token)
    """
    Upload a file.

    - id: Unique identifier (filename without extension recommended)
    - type: 'audio' or 'video'
    - tags: JSON array string (e.g., '["todo"]' for audio, '["FB","TT"]' for video)
    
    Video overwrite behavior:
    - Same title → 409 CONFLICT
    - Different title → overwrite (delete old, insert new)
    - Returns "overwritten": true in response
    
    Audio behavior:
    - Always 409 on duplicate (strict, no overwrite)
    """
    # Sanitize file ID to prevent path traversal
    id = sanitize_file_id(id)
    if not id:
        raise HTTPException(400, "Invalid file ID")
    
    conn = get_db()
    overwritten = False
    
    # Check if ID+TYPE+PROJECT combination already exists with full details
    existing = conn.execute(
        'SELECT id, title, mime_type, file_size, duration FROM files WHERE id = ? AND project = ? AND type = ?',
        (id, project, type)
    ).fetchone()
    
    if existing:
        # Audio: always 409 (strict, no overwrite)
        if type == 'audio':
            conn.close()
            raise HTTPException(409, f"Audio file with id '{id}' already exists")
        
        # Video: compare titles to determine overwrite
        old_title = normalize_title(existing['title'])
        new_title = normalize_title(title)
        
        if old_title == new_title:
            # Same title → 409 CONFLICT
            conn.close()
            raise HTTPException(409, "Video with same title already exists")
        else:
            # Different title → OVERWRITE
            print(f"[OVERWRITE] Video '{id}': title changed from '{old_title}' to '{new_title}'")
            
            # Delete old physical file
            old_ext = get_file_extension(existing['mime_type'])
            old_path = resolve_file_path(type, project, id, old_ext)
            if old_path.exists():
                try:
                    old_path.unlink()
                    print(f"[OVERWRITE] Deleted old file: {old_path}")
                except Exception as e:
                    print(f"[OVERWRITE WARNING] Failed to delete old file {old_path}: {e}")
            
            # Delete from database
            conn.execute('DELETE FROM files WHERE id = ? AND project = ? AND type = ?', (id, project, type))
            conn.commit()
            overwritten = True

    # Parse and validate tags
    try:
        tag_list = json.loads(tags)
        if not isinstance(tag_list, list):
            raise ValueError("Tags must be an array")
    except (json.JSONDecodeError, ValueError) as e:
        conn.close()
        raise HTTPException(400, f"Invalid tags format: {e}")

    # Validate audio tags
    if type == 'audio':
        tag_list = validate_audio_tags(tag_list)

    # If empty tags, auto-set to "all"
    if not tag_list or tag_list == []:
        tag_list = ['all']

    # Save file to storage (project-prefixed path)
    storage_subdir = STORAGE_DIR / type / project
    storage_subdir.mkdir(parents=True, exist_ok=True)
    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File too large (max {MAX_FILE_SIZE} bytes)")

    # Write to temp file to check MIME type
    temp_path = storage_subdir / f"temp_{id}"
    temp_path.write_bytes(content)

    mime = get_mime_type(temp_path)
    if mime not in ALLOWED_MIME:
        temp_path.unlink()
        raise HTTPException(400, f"Invalid file type: {mime}")

    # Determine extension and move to final location
    ext = get_file_extension(mime)
    final_filename = f"{id}{ext}"
    final_path = storage_subdir / final_filename
    temp_path.rename(final_path)

    # Get duration via ffprobe
    duration = 0
    try:
        import subprocess
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(final_path)],
            capture_output=True, text=True
        )
        duration = int(float(result.stdout.strip()))
    except Exception:
        pass

    # Insert into database
    conn.execute('''
        INSERT INTO files (id, project, type, title, tags, duration, file_size, mime_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (id, project, type, title, json.dumps(tag_list), duration, len(content), mime))
    conn.commit()
    conn.close()

    return UploadResponse(ok=True, id=id, type=type, overwritten=overwritten)


@app.put("/{token}/{project}/api/files/{id}")
def update_file(
    token: str,
    project: str,
    id: str,
    request: UpdateFileRequest,
    type: Literal['audio', 'video'] = Query(..., description="File type (audio or video) - required for safety")
):
    verify_token(token)
    """
    Update file tags and/or title.

    For audio: Only fixed tags allowed (todo, ready, all, trash, delivered)
    For video: Any tags allowed
    
    Query param 'type' is ALWAYS required to prevent accidental updates.
    """
    # Sanitize file ID to prevent path traversal
    id = sanitize_file_id(id)
    if not id:
        raise HTTPException(400, "Invalid file ID")
    
    conn = get_db()

    # Check file exists with the specified type
    row = conn.execute(
        'SELECT type FROM files WHERE id = ? AND project = ? AND type = ?',
        (id, project, type)
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(404, f"File '{id}' of type '{type}' not found")

    # Validate tags based on type
    tags = request.tags
    if row['type'] == 'audio':
        tags = validate_audio_tags(tags)

    # If all tags removed (empty array), auto-set to "all"
    if not tags or tags == []:
        tags = ['all']

    # Update tags and optionally title - include type to ensure we update the right row
    if request.title is not None:
        conn.execute(
            'UPDATE files SET tags = ?, title = ? WHERE id = ? AND project = ? AND type = ?',
            (json.dumps(tags), request.title, id, project, row['type'])
        )
    else:
        conn.execute(
            'UPDATE files SET tags = ? WHERE id = ? AND project = ? AND type = ?',
            (json.dumps(tags), id, project, row['type'])
        )
    conn.commit()
    conn.close()

    return {"ok": True, "id": id, "tags": tags, "title": request.title}


@app.delete("/{token}/{project}/api/files/{id}")
def delete_file(
    token: str,
    project: str,
    id: str,
    type: Literal['audio', 'video'] = Query(..., description="File type (audio or video) - required for safety")
):
    verify_token(token)
    """
    Delete a file permanently (only allowed for trashed files).
    
    Query param 'type' is ALWAYS required to prevent accidental deletion.
    """
    # Sanitize file ID to prevent path traversal
    id = sanitize_file_id(id)
    if not id:
        raise HTTPException(400, "Invalid file ID")
    
    conn = get_db()

    # Check file exists and is trashed with the specified type
    row = conn.execute(
        'SELECT type, tags, mime_type FROM files WHERE id = ? AND project = ? AND type = ?',
        (id, project, type)
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(404, f"File '{id}' of type '{type}' not found")

    tags = json.loads(row['tags'])
    if 'trash' not in tags:
        conn.close()
        raise HTTPException(400, "Only trashed files can be deleted. Add 'trash' tag first.")

    # Delete physical file (dual-path: check both new and old locations)
    file_type = row['type']
    ext = get_file_extension(row['mime_type'])
    file_path = resolve_file_path(file_type, project, id, ext)
    if file_path.exists():
        file_path.unlink()
    else:
        # Fallback: try all extensions (for legacy files where mime_type might be wrong)
        for ext in MIME_TO_EXT.values():
            legacy_path = STORAGE_DIR / file_type / f"{id}{ext}"
            if legacy_path.exists():
                legacy_path.unlink()
                break

    # Delete from database - include type to ensure we delete the correct row
    conn.execute('DELETE FROM files WHERE id = ? AND project = ? AND type = ?', (id, project, file_type))
    conn.commit()
    conn.close()

    return {"ok": True, "id": id, "deleted": True}


@app.get("/{token}/{project}/stream/{id}")
async def stream_file(token: str, project: str, id: str, request: Request, type: Literal['audio', 'video'] = Query(..., description="File type (audio or video) - required for safety")):
    verify_token(token)
    """
    Stream a file by ID with HTTP range support for video/audio playback.
    
    Query param 'type' is REQUIRED to prevent streaming wrong file type.
    """
    # URL decode the ID (handles spaces and special characters)
    from urllib.parse import unquote
    decoded_id = unquote(id)
    
    # Sanitize file ID to prevent path traversal
    decoded_id = sanitize_file_id(decoded_id)
    
    conn = get_db()
    row = conn.execute(
        'SELECT type, mime_type, tags, title FROM files WHERE id = ? AND project = ? AND type = ?',
        (decoded_id, project, type)
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(404, f"File '{decoded_id}' not found")

    # Don't stream trashed files
    tags = json.loads(row['tags'])
    if 'trash' in tags:
        raise HTTPException(404, "File is in trash")

    # Find the physical file - dual-path support (new location preferred)
    file_type = row['type']
    # Get the correct extension for this MIME type
    ext = MIME_TO_EXT.get(row['mime_type'], '.bin')
    file_path = resolve_file_path(file_type, project, decoded_id, ext)
    
    if not file_path.exists():
        raise HTTPException(404, f"File content not found: {decoded_id}{ext}")
    
    # Determine download filename: use title (sanitized) if available, otherwise use ID
    title = row['title'] or ""
    safe_title = sanitize_filename(title)
    if safe_title:
        download_filename = f"{safe_title}{ext}"
    else:
        download_filename = f"{decoded_id}{ext}"
    
    # Use FileResponse (handles HTTP range requests for seeking)
    return FileResponse(
        file_path,
        media_type=row['mime_type'],
        filename=download_filename
    )




@app.get("/{token}/{project}/static/{filepath:path}")
def serve_static(token: str, project: str, filepath: str):
    """Serve static files (JS/CSS) with token authentication."""
    verify_token(token)
    static_file = Path(__file__).parent / 'static' / filepath
    # Security: ensure path doesn't escape static directory
    try:
        static_file.resolve().relative_to((Path(__file__).parent / 'static').resolve())
    except ValueError:
        raise HTTPException(403, "Invalid path")
    if not static_file.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(static_file)

# API endpoints start with /api/ or /stream/
# Everything else serves the SPA (for client-side routing)
@app.get("/{token}/{project}/")
@app.get("/{token}/{project}/{path:path}")
def serve_spa(token: str, project: str, path: str = ""):
    """
    Serve the SPA for all routes.
    This enables client-side routing without hashes.
    API and stream routes are handled by their specific endpoints above.
    """
    verify_token(token)
    static_path = Path(__file__).parent / 'static' / 'index.html'
    return FileResponse(static_path)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8080)
