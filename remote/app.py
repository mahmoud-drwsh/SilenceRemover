#!/usr/bin/env python3
"""
Media Manager Backend
FastAPI service for audio/video file management with tag-based organization.

Environment variables:
    MEDIA_TOKEN - Optional one-time bootstrap token for projects
    ADMIN_TOKEN - Optional one-time bootstrap token for admin dashboard
    SUPABASE_DATABASE_URL - Postgres connection string for metadata (required)
    S3_ENDPOINT_URL / S3_BUCKET / S3_ACCESS_KEY / S3_SECRET_KEY / S3_REGION - S3-compatible storage (required)
"""

import os
import json
import secrets
import hashlib
import hmac
import tempfile
import magic
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from datetime import date, datetime
from contextlib import asynccontextmanager
from typing import Any, List, Optional, Literal
from urllib.parse import quote

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

# Config
BOOTSTRAP_MEDIA_TOKEN = os.environ.get('MEDIA_TOKEN')
BOOTSTRAP_ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN')
SUPABASE_DATABASE_URL = os.environ.get('SUPABASE_DATABASE_URL')
SUPABASE_DB_SCHEMA = os.environ.get('SUPABASE_DB_SCHEMA', 'media_manager')
S3_ENDPOINT_URL = os.environ.get('S3_ENDPOINT_URL')
S3_BUCKET = os.environ.get('S3_BUCKET', 'media-manager')
S3_ACCESS_KEY = os.environ.get('S3_ACCESS_KEY')
S3_SECRET_KEY = os.environ.get('S3_SECRET_KEY')
S3_REGION = os.environ.get('S3_REGION', 'eu2')
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB


def quote_ident(identifier: str) -> str:
    """Quote a trusted Postgres identifier from env/config."""
    if not identifier or not identifier.replace("_", "").isalnum() or identifier[0].isdigit():
        raise RuntimeError(f"Unsafe Postgres identifier: {identifier!r}")
    return '"' + identifier.replace('"', '""') + '"'


SUPABASE_SCHEMA_IDENT = quote_ident(SUPABASE_DB_SCHEMA)


def _to_api_scalar(value: Any) -> Any:
    """Normalize DB driver values to the shapes the existing API expects."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return value


class PgResult:
    """Small psycopg result adapter matching the endpoint fetch calls."""

    def __init__(self, cursor):
        self.cursor = cursor

    def _row(self, row):
        if row is None:
            return None
        return {key: _to_api_scalar(value) for key, value in row.items()}

    def fetchone(self):
        return self._row(self.cursor.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self.cursor.fetchall()]


@dataclass
class PgConnection:
    """Tiny DB-API-ish wrapper for the Supabase/Postgres metadata store."""

    conn: Any

    def _normalize_sql(self, sql: str) -> str:
        normalized = sql.replace("?", "%s")
        normalized = normalized.replace("FROM files", f"FROM {SUPABASE_SCHEMA_IDENT}.files")
        normalized = normalized.replace("INTO files", f"INTO {SUPABASE_SCHEMA_IDENT}.files")
        normalized = normalized.replace("UPDATE files", f"UPDATE {SUPABASE_SCHEMA_IDENT}.files")
        normalized = normalized.replace("DELETE FROM files", f"DELETE FROM {SUPABASE_SCHEMA_IDENT}.files")
        normalized = normalized.replace("tags NOT LIKE", "tags::text NOT LIKE")
        normalized = normalized.replace("tags LIKE", "tags::text LIKE")
        return normalized

    def _normalize_params(self, sql: str, params: Any):
        if params is None:
            return None
        if not isinstance(params, (list, tuple)):
            return params
        if "tags" not in sql.lower():
            return params

        from psycopg.types.json import Jsonb

        normalized = []
        for value in params:
            if isinstance(value, str) and value.startswith("[") and value.endswith("]"):
                try:
                    normalized.append(Jsonb(json.loads(value)))
                    continue
                except json.JSONDecodeError:
                    pass
            normalized.append(value)
        return tuple(normalized)

    def execute(self, sql: str, params: Any = None):
        cur = self.conn.cursor()
        cur.execute(self._normalize_sql(sql), self._normalize_params(sql, params))
        return PgResult(cur)

    def executescript(self, _sql: str):
        # Supabase schema is managed outside app startup.
        return None

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def _generate_token() -> str:
    """Generate a new secure random token string."""
    return secrets.token_urlsafe(32)


def _token_hash(token: str) -> str:
    """Return the database-safe hash for a token without storing plaintext."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_table_name() -> str:
    return f"{SUPABASE_SCHEMA_IDENT}.auth_tokens"


def _bootstrap_auth_tokens(conn: PgConnection):
    """Seed Supabase auth tokens from env only when rows are missing."""
    bootstrap = {
        "media": BOOTSTRAP_MEDIA_TOKEN,
        "admin": BOOTSTRAP_ADMIN_TOKEN,
    }
    for kind, token in bootstrap.items():
        existing = conn.execute(
            f"SELECT 1 FROM {_auth_table_name()} WHERE kind = ?",
            (kind,),
        ).fetchone()
        if existing:
            continue
        if not token:
            raise RuntimeError(f"{kind.upper()} token is missing from Supabase and no bootstrap env token was provided")
        conn.execute(
            f"""
            INSERT INTO {_auth_table_name()} (kind, token_hash)
            VALUES (?, ?)
            ON CONFLICT (kind) DO NOTHING
            """,
            (kind, _token_hash(token)),
        )
    conn.commit()


def _get_token_hash(kind: str) -> str | None:
    conn = get_db()
    try:
        row = conn.execute(
            f"SELECT token_hash FROM {_auth_table_name()} WHERE kind = ?",
            (kind,),
        ).fetchone()
        return row["token_hash"] if row else None
    finally:
        conn.close()


def _verify_stored_token(kind: str, token: str) -> bool:
    stored_hash = _get_token_hash(kind)
    if not stored_hash:
        return False
    return hmac.compare_digest(stored_hash, _token_hash(token))


def _rotate_token(kind: str) -> str:
    """Rotate a token in Supabase and return the plaintext value once."""
    new_token = _generate_token()
    conn = get_db()
    try:
        row = conn.execute(
            f"""
            UPDATE {_auth_table_name()}
            SET token_hash = ?, rotated_at = now(), version = version + 1
            WHERE kind = ?
            RETURNING version
            """,
            (_token_hash(new_token), kind),
        ).fetchone()
        if not row:
            conn.execute(
                f"INSERT INTO {_auth_table_name()} (kind, token_hash) VALUES (?, ?)",
                (kind, _token_hash(new_token)),
            )
        conn.commit()
        return new_token
    finally:
        conn.close()

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
AUDIO_TAGS = {'todo', 'ready', 'all', 'trash'}


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
    """Verify the Supabase/Postgres metadata store is reachable."""
    if not SUPABASE_DATABASE_URL:
        raise RuntimeError("SUPABASE_DATABASE_URL must be set")

    conn = get_db()
    conn.execute(f"SELECT 1 FROM {SUPABASE_SCHEMA_IDENT}.files LIMIT 1").fetchone()
    conn.execute(f"SELECT 1 FROM {_auth_table_name()} LIMIT 1").fetchone()
    _bootstrap_auth_tokens(conn)
    conn.close()


def get_db():
    """Get a Supabase/Postgres metadata connection."""
    if not SUPABASE_DATABASE_URL:
        raise RuntimeError("SUPABASE_DATABASE_URL must be set")
    import psycopg
    from psycopg.rows import dict_row

    return PgConnection(psycopg.connect(SUPABASE_DATABASE_URL, row_factory=dict_row))


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


def storage_object_key(file_type: str, project: str, file_id: str, ext: str) -> str:
    """Return the S3 object key matching the existing storage tree layout."""
    return f"{file_type}/{project}/{file_id}{ext}"


def get_s3_client():
    """Create an S3 client for the configured S3-compatible endpoint."""
    if not S3_ENDPOINT_URL or not S3_ACCESS_KEY or not S3_SECRET_KEY:
        raise RuntimeError("S3_ENDPOINT_URL, S3_ACCESS_KEY, and S3_SECRET_KEY must be set")
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_storage_backend_ready():
    """Fail startup early if S3 storage is not usable."""
    get_s3_client().head_bucket(Bucket=S3_BUCKET)


def storage_delete(file_type: str, project: str, file_id: str, ext: str):
    """Delete one object from S3."""
    get_s3_client().delete_object(Bucket=S3_BUCKET, Key=storage_object_key(file_type, project, file_id, ext))


def storage_delete_any_extension(file_type: str, project: str, file_id: str) -> bool:
    """Best-effort delete for legacy rows whose stored MIME may imply the wrong extension."""
    deleted = False
    for ext in set(MIME_TO_EXT.values()):
        try:
            storage_delete(file_type, project, file_id, ext)
            deleted = True
        except Exception:
            continue
    return deleted


def storage_put_bytes(file_type: str, project: str, file_id: str, ext: str, content: bytes, mime: str):
    """Write bytes to S3."""
    get_s3_client().put_object(
        Bucket=S3_BUCKET,
        Key=storage_object_key(file_type, project, file_id, ext),
        Body=content,
        ContentType=mime,
    )


def storage_project_size_totals() -> dict[str, int]:
    """Return exact object-byte totals per project by listing S3 storage."""
    client = get_s3_client()
    totals: dict[str, int] = defaultdict(int)

    for file_type in ("audio", "video"):
        prefix = f"{file_type}/"
        continuation_token = None
        while True:
            kwargs = {"Bucket": S3_BUCKET, "Prefix": prefix}
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token

            page = client.list_objects_v2(**kwargs)
            for obj in page.get("Contents", []):
                key = obj.get("Key", "")
                parts = key.split("/", 2)
                if len(parts) < 3 or not parts[1] or key.endswith("/"):
                    continue
                totals[parts[1]] += int(obj.get("Size", 0) or 0)

            if not page.get("IsTruncated"):
                break
            continuation_token = page.get("NextContinuationToken")
            if not continuation_token:
                break

    return dict(totals)


def _parse_range_header(range_header: Optional[str], size: int) -> tuple[int, int] | None:
    """Parse a single HTTP bytes range into inclusive start/end offsets."""
    if not range_header or not range_header.startswith("bytes="):
        return None
    raw_range = range_header.removeprefix("bytes=").split(",", 1)[0].strip()
    if "-" not in raw_range:
        return None
    start_raw, end_raw = raw_range.split("-", 1)
    if not start_raw:
        try:
            suffix_len = int(end_raw)
        except ValueError:
            return None
        if suffix_len <= 0:
            return None
        return max(size - suffix_len, 0), size - 1
    try:
        start = int(start_raw)
        end = int(end_raw) if end_raw else size - 1
    except ValueError:
        return None
    if start >= size or end < start:
        return None
    return start, min(end, size - 1)


def storage_stream_response(
    request: Request,
    file_type: str,
    project: str,
    file_id: str,
    ext: str,
    mime: str,
    download_filename: str,
):
    """Build a streaming response from S3."""
    client = get_s3_client()
    key = storage_object_key(file_type, project, file_id, ext)
    try:
        head = client.head_object(Bucket=S3_BUCKET, Key=key)
    except Exception:
        raise HTTPException(404, f"File content not found: {file_id}{ext}")

    size = int(head.get("ContentLength", 0))
    byte_range = _parse_range_header(request.headers.get("range"), size)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(download_filename)}",
    }
    get_kwargs = {"Bucket": S3_BUCKET, "Key": key}
    status_code = 200
    if byte_range:
        start, end = byte_range
        get_kwargs["Range"] = f"bytes={start}-{end}"
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(end - start + 1)
        status_code = 206
    else:
        headers["Content-Length"] = str(size)

    obj = client.get_object(**get_kwargs)
    return StreamingResponse(
        obj["Body"].iter_chunks(chunk_size=1024 * 1024),
        status_code=status_code,
        media_type=mime,
        headers=headers,
    )


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
    ensure_storage_backend_ready()
    yield


app = FastAPI(
    title="Media Manager",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def verify_token(token: str):
    """Verify the provided token matches the Supabase-backed media token."""
    if not _verify_stored_token("media", token):
        raise HTTPException(401, "Invalid token")


def verify_admin_token(admin_token: str):
    """Verify the provided token matches the Supabase-backed admin token."""
    if not _verify_stored_token("admin", admin_token):
        raise HTTPException(401, "Invalid admin token")


def get_current_plaintext_media_token() -> str | None:
    """Return the bootstrap media token only while it still matches Supabase."""
    if BOOTSTRAP_MEDIA_TOKEN and _verify_stored_token("media", BOOTSTRAP_MEDIA_TOKEN):
        return BOOTSTRAP_MEDIA_TOKEN
    return None


# API Endpoints
@app.get("/projects/{token}/{project}/api/files", response_model=List[FileResponseModel])
def list_files(
    token: str,
    project: str,
    type: Optional[Literal['audio', 'video']] = Query(None, description="Filter by type"),
    tags: Optional[str] = Query(None, description="Comma-separated tags (AND logic)"),
    sort: Optional[Literal['asc', 'desc']] = Query('asc', description="Sort order: asc or desc"),
    check_id: Optional[str] = Query(None, description="Pre-flight: check specific ID for existence"),
    check_title: Optional[str] = Query(None, description="Pre-flight: check if title matches (requires check_id)"),
    include_trash: bool = Query(False, description="Include trashed files in results (default: false)"),
    include_pending: bool = Query(False, description="Include pending review files in results (default: false)")
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
        # No tags specified (ALL tab) - exclude trash and pending by default
        if not include_trash:
            conditions.append("tags NOT LIKE ?")
            params.append('"%"trash"%"')
        if not include_pending and 'pending' not in (tag_list or []):
            conditions.append("tags NOT LIKE ?")
            params.append('"%"pending"%"')

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


@app.post("/projects/{token}/{project}/api/files", response_model=UploadResponse)
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
            try:
                storage_delete(type, project, id, old_ext)
                print(f"[OVERWRITE] Deleted old stored object: {storage_object_key(type, project, id, old_ext)}")
            except Exception as e:
                print(f"[OVERWRITE WARNING] Failed to delete old stored object {id}{old_ext}: {e}")
            
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

    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File too large (max {MAX_FILE_SIZE} bytes)")

    # Write to temp file to check MIME type
    temp_file = tempfile.NamedTemporaryFile(prefix=f"media-manager-{id}-", delete=False)
    temp_path = Path(temp_file.name)
    try:
        temp_file.write(content)
        temp_file.close()

        mime = get_mime_type(temp_path)
        if mime not in ALLOWED_MIME:
            raise HTTPException(400, f"Invalid file type: {mime}")

        # Determine extension before persisting to the active storage backend.
        ext = get_file_extension(mime)

        # Get duration via ffprobe
        duration = 0
        try:
            import subprocess
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', str(temp_path)],
                capture_output=True, text=True
            )
            duration = int(float(result.stdout.strip()))
        except Exception:
            pass

        storage_put_bytes(type, project, id, ext, content, mime)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass

    # Insert into database
    conn.execute('''
        INSERT INTO files (id, project, type, title, tags, duration, file_size, mime_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (id, project, type, title, json.dumps(tag_list), duration, len(content), mime))
    conn.commit()
    conn.close()

    return UploadResponse(ok=True, id=id, type=type, overwritten=overwritten)


@app.put("/projects/{token}/{project}/api/files/{id}")
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

    For audio: Only fixed tags allowed (todo, ready, all, trash)
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


@app.delete("/projects/{token}/{project}/api/files/{id}")
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

    # Delete stored object/file from the active backend.
    file_type = row['type']
    ext = get_file_extension(row['mime_type'])
    try:
        storage_delete(file_type, project, id, ext)
    except Exception:
        storage_delete_any_extension(file_type, project, id)

    # Delete from database - include type to ensure we delete the correct row
    conn.execute('DELETE FROM files WHERE id = ? AND project = ? AND type = ?', (id, project, file_type))
    conn.commit()
    conn.close()

    return {"ok": True, "id": id, "deleted": True}


@app.get("/projects/{token}/{project}/stream/{id}")
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

    file_type = row['type']
    # Get the correct extension for this MIME type
    ext = MIME_TO_EXT.get(row['mime_type'], '.bin')

    # Determine download filename: use title (sanitized) if available, otherwise use ID
    title = row['title'] or ""
    safe_title = sanitize_filename(title)
    if safe_title:
        download_filename = f"{safe_title}{ext}"
    else:
        download_filename = f"{decoded_id}{ext}"
    
    return storage_stream_response(
        request,
        file_type,
        project,
        decoded_id,
        ext,
        row['mime_type'],
        download_filename,
    )




@app.get("/projects/{token}/{project}/video-player")
def serve_video_player(token: str, project: str):
    """Serve dedicated video player page (opened in a new tab)."""
    verify_token(token)
    player_page = Path(__file__).parent / 'static' / 'video-player.html'
    return FileResponse(player_page)


@app.get("/projects/{token}/{project}/static/{filepath:path}")
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

# API endpoints start with /projects/ or /admin/
# Everything else serves the SPA (for client-side routing)
@app.get("/projects/{token}/{project}/")
@app.get("/projects/{token}/{project}/{path:path}")
def serve_spa(token: str, project: str, path: str = ""):
    """
    Serve the SPA for all routes.
    This enables client-side routing without hashes.
    API and stream routes are handled by their specific endpoints above.
    """
    verify_token(token)
    static_path = Path(__file__).parent / 'static' / 'index.html'
    return FileResponse(static_path)


# Admin Dashboard Endpoints
@app.post("/admin/{admin_token}/api/refresh-token")
@app.post("/admin/{admin_token}/api/refresh-admin-token")
def refresh_admin_token(admin_token: str):
    """
    Rotate the admin token in Supabase and return the plaintext token once.
    """
    verify_admin_token(admin_token)

    new_admin_token = _rotate_token("admin")
    return {
        "admin_token": new_admin_token,
        "media_token": get_current_plaintext_media_token(),
        "admin_url": f"/admin/{new_admin_token}/",
        "persisted": True,
        "persistence": "supabase"
    }


@app.post("/admin/{admin_token}/api/refresh-media-token")
def refresh_media_token(admin_token: str):
    """
    Rotate the media/project token in Supabase and return the plaintext token once.
    """
    verify_admin_token(admin_token)

    new_media_token = _rotate_token("media")
    return {
        "admin_token": admin_token,
        "media_token": new_media_token,
        "persisted": True,
        "persistence": "supabase"
    }


@app.get("/admin/{admin_token}/api/projects")
def list_admin_projects(admin_token: str):
    """
    Admin endpoint: List all projects with aggregated stats.
    
    Returns per-project stats:
    - Audio counts: todo, ready, trash, total
    - Video total count
    - Total storage bytes
    - Last updated timestamp
    """
    verify_admin_token(admin_token)
    
    conn = get_db()
    
    # Aggregate query for project stats
    rows = conn.execute('''
        SELECT 
            project,
            COUNT(CASE WHEN type='audio' THEN 1 END) as audio_total,
            SUM(CASE WHEN type='audio' AND tags LIKE '%"todo"%' THEN 1 ELSE 0 END) as audio_todo,
            SUM(CASE WHEN type='audio' AND tags LIKE '%"ready"%' THEN 1 ELSE 0 END) as audio_ready,
            SUM(CASE WHEN type='audio' AND tags LIKE '%"trash"%' THEN 1 ELSE 0 END) as audio_trash,
            COUNT(CASE WHEN type='video' THEN 1 END) as video_total,
            COALESCE(SUM(file_size), 0) as total_bytes,
            MAX(created_at) as last_updated
        FROM files 
        GROUP BY project
        ORDER BY project
    ''').fetchall()
    conn.close()
    
    projects = []
    for row in rows:
        projects.append({
            "project": row['project'],
            "audio": {
                "todo": row['audio_todo'] or 0,
                "ready": row['audio_ready'] or 0,
                "trash": row['audio_trash'] or 0,
                "total": row['audio_total'] or 0
            },
            "video": {
                "total": row['video_total'] or 0
            },
            "storage_bytes": row['total_bytes'] or 0,
            "last_updated": row['last_updated']
        })
    
    return {
        "media_token": get_current_plaintext_media_token(),
        "projects": projects
    }


@app.get("/admin/{admin_token}/api/projects/s3-storage")
def list_admin_project_s3_storage(admin_token: str):
    """
    Admin endpoint: List exact S3 object-byte totals by project.

    This is separate from the main project list so the dashboard can render
    immediately from database metadata, then fill in S3 totals.
    """
    verify_admin_token(admin_token)
    totals = storage_project_size_totals()
    return {
        "projects": [
            {
                "project": project,
                "s3_storage_bytes": size,
            }
            for project, size in sorted(totals.items())
        ],
        "total_s3_storage_bytes": sum(totals.values()),
    }


@app.api_route(
    "/admin/{admin_token}/files",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
)
@app.api_route(
    "/admin/{admin_token}/files/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
)
def removed_admin_file_browser(admin_token: str, path: Optional[str] = None):
    """Return a clear 404 for the removed admin File Browser route."""
    verify_admin_token(admin_token)
    raise HTTPException(404, "Admin File Browser has been removed")


@app.get("/admin/{admin_token}/")
@app.get("/admin/{admin_token}/{path:path}")
def serve_admin(admin_token: str, path: str = ""):
    """
    Serve the admin dashboard SPA.
    All admin routes lead to the same HTML (client-side routing).
    """
    verify_admin_token(admin_token)
    admin_path = Path(__file__).parent / 'static' / 'admin.html'
    return FileResponse(admin_path)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8080)
