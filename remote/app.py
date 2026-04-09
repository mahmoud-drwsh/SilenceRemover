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


def init_db():
    """Initialize database with tag-based schema.
    
    Note: For migrating from old Flask schema (ready/trashed columns),
    use scripts/migrate-db.py separately before starting the service.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (STORAGE_DIR / 'audio').mkdir(parents=True, exist_ok=True)
    (STORAGE_DIR / 'video').mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
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
    tags: Optional[str] = Query(None, description="Comma-separated tags (AND logic)")
):
    verify_token(token)
    """
    List files with optional filtering.

    - No tags: Returns all files except those with 'trash' tag
    - tags=trash: Returns only trashed files
    - tags=FB,TT: Returns files with BOTH tags (AND logic)
    """
    conn = get_db()
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

    rows = conn.execute(
        f'''
        SELECT id, project, type, title, tags, duration, file_size, mime_type, created_at
        FROM files
        WHERE {where_clause}
        ORDER BY created_at DESC
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
    """
    conn = get_db()

    # Check if ID+TYPE combination already exists (allows same ID for audio vs video)
    existing = conn.execute(
        'SELECT id FROM files WHERE id = ? AND project = ? AND type = ?',
        (id, project, type)
    ).fetchone()
    if existing:
        conn.close()
        raise HTTPException(409, f"File with id '{id}' and type '{type}' already exists")

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

    # Save file to storage
    storage_subdir = STORAGE_DIR / type
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

    return UploadResponse(ok=True, id=id, type=type)


@app.put("/{token}/{project}/api/files/{id}")
def update_file(
    token: str,
    project: str,
    id: str,
    request: UpdateFileRequest
):
    verify_token(token)
    """
    Update file tags and/or title.

    For audio: Only fixed tags allowed (todo, ready, all, trash, delivered)
    For video: Any tags allowed
    """
    conn = get_db()

    # Check file exists
    row = conn.execute(
        'SELECT type FROM files WHERE id = ? AND project = ?',
        (id, project)
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(404, f"File '{id}' not found")

    # Validate tags based on type
    tags = request.tags
    if row['type'] == 'audio':
        tags = validate_audio_tags(tags)

    # If all tags removed (empty array), auto-set to "all"
    if not tags or tags == []:
        tags = ['all']

    # Update tags and optionally title
    if request.title is not None:
        conn.execute(
            'UPDATE files SET tags = ?, title = ? WHERE id = ? AND project = ?',
            (json.dumps(tags), request.title, id, project)
        )
    else:
        conn.execute(
            'UPDATE files SET tags = ? WHERE id = ? AND project = ?',
            (json.dumps(tags), id, project)
        )
    conn.commit()
    conn.close()

    return {"ok": True, "id": id, "tags": tags, "title": request.title}


@app.delete("/{token}/{project}/api/files/{id}")
def delete_file(token: str, project: str, id: str):
    verify_token(token)
    """
    Delete a file permanently (only allowed for trashed files).
    """
    conn = get_db()

    # Check file exists and is trashed
    row = conn.execute(
        'SELECT type, tags FROM files WHERE id = ? AND project = ?',
        (id, project)
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(404, f"File '{id}' not found")

    tags = json.loads(row['tags'])
    if 'trash' not in tags:
        conn.close()
        raise HTTPException(400, "Only trashed files can be deleted. Add 'trash' tag first.")

    # Delete physical file
    file_type = row['type']
    for ext in MIME_TO_EXT.values():
        file_path = STORAGE_DIR / file_type / f"{id}{ext}"
        if file_path.exists():
            file_path.unlink()
            break

    # Delete from database
    conn.execute('DELETE FROM files WHERE id = ? AND project = ?', (id, project))
    conn.commit()
    conn.close()

    return {"ok": True, "id": id, "deleted": True}


@app.get("/{token}/{project}/stream/{id}")
async def stream_file(token: str, project: str, id: str, request: Request, type: str = Query(default="video", enum=["audio", "video"])):
    verify_token(token)
    """
    Stream a file by ID with HTTP range support for video/audio playback.
    
    Query param 'type' determines whether to stream audio or video.
    Default is 'video' for the video player.
    """
    # URL decode the ID (handles spaces and special characters)
    from urllib.parse import unquote
    decoded_id = unquote(id)
    
    conn = get_db()
    row = conn.execute(
        'SELECT type, mime_type, tags FROM files WHERE id = ? AND project = ? AND type = ?',
        (decoded_id, project, type)
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(404, f"File '{decoded_id}' not found")

    # Don't stream trashed files
    tags = json.loads(row['tags'])
    if 'trash' in tags:
        raise HTTPException(404, "File is in trash")

    # Find the physical file - ONLY look for the expected type
    file_type = row['type']
    # Get the correct extension for this MIME type
    ext = MIME_TO_EXT.get(row['mime_type'], '.bin')
    file_path = STORAGE_DIR / file_type / f"{decoded_id}{ext}"
    
    if not file_path.exists():
        raise HTTPException(404, f"File content not found: {decoded_id}{ext}")
    
    # Use StreamingResponse with HTTP range support
    from fastapi.responses import StreamingResponse
    import aiofiles
    
    async def file_iterator():
        async with aiofiles.open(file_path, 'rb') as f:
            while chunk := await f.read(8192):
                yield chunk
    
    return StreamingResponse(
        file_iterator(),
        media_type=row['mime_type'],
        headers={
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{decoded_id}{ext}"'
        }
    )


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
