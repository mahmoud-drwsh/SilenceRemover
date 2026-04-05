# MP3 Manager Integration - Implementation Summary

## Overview
Integrated the MP3 Manager VPS system with the SilenceRemover pipeline for two-way title synchronization.

## Architecture
```
┌─────────────────┐     API Fetch      ┌──────────────────┐
│  MP3 Manager    │ ←────────────────→ │  Pipeline Sync   │
│  (VPS Web UI)   │   (titles only)    │  (at start)      │
│                 │                    │                  │
│  User edits     │     API Upload     │  After Phase 2   │
│  titles via     │ ←────────────────→ │  (snippet+title) │
│  browser        │   (idempotent)     │                  │
└─────────────────┘                    └──────────────────┘
         ↑                                      ↓
         └──────────── Reads title.txt ──────────┘
                           (Phase 3)
```

## New Black Box Package: `sr_mp3_manager`

### Files Created
1. **`packages/sr_mp3_manager/__init__.py`** - Public exports
2. **`packages/sr_mp3_manager/api.py`** - HTTP client with URL parsing
3. **`packages/sr_mp3_manager/sync.py`** - Title comparison and sync logic
4. **`packages/sr_mp3_manager/upload.py`** - Idempotent upload logic

### Public API
```python
from sr_mp3_manager import Mp3ApiClient, sync_titles, ensure_uploaded

# Parse full URL
client = Mp3ApiClient("https://example.com/TOKEN/PROJECT/")

# Sync: API → local .txt (returns changed IDs)
updated = sync_titles(client, titles_dir, completed_dir)

# Upload: idempotent (checks existence first)
sure_uploaded(client, file_id, title, audio_path)
```

## Pipeline Integration

### Hook 1: Pre-flight Sync (`src/app/pipeline.py`)
**Location:** Start of `run()` function
**Logic:**
1. If `MP3_MANAGER_URL` env var set
2. Fetch all titles from API
3. Compare to local `title/{id}.txt`
4. If different: overwrite .txt, delete `completed/{id}.json`
5. Log updated count

### Hook 2: Post-Phase 2 Upload
**Location:** Inside `run_title_phase()` after title generation
**Logic:**
1. After AI title generated and saved to .txt
2. Check if file_id exists on MP3 Manager via HEAD request
3. If not exists: upload snippet + title
4. If exists: skip (idempotent)

### ID Format
- **Exact filename with extension**: `video.mp4` → ID: `"video.mp4"`
- **Completed marker**: `completed/video.mp4.json`
- **Title file**: `titles/video.mp4.txt`

## MP3 Manager API Endpoints

### `GET /<token>/<project>/api/files`
Returns all files for sync:
```json
[
  {"id": "video.mp4", "title": "...", "ready": true, "trashed": false}
]
```

### `HEAD /<token>/<project>/api/files/<id>`
Returns 200 if exists, 404 if not (for idempotent check)

### `POST /<token>/<project>/api/upload`
Idempotent upload:
- Form fields: `id`, `title`
- File field: `file` or `audio`
- If exists: updates title only, returns `{"updated": true}`
- If new: saves file, returns `{"created": true}`, 201

## Configuration

### Environment Variable
```bash
MP3_MANAGER_URL=https://example.com/TOKEN/PROJECT/
```

Single URL contains token and project path.

## Behavior Summary

| Scenario | Action |
|----------|--------|
| User edits title in web UI | Next pipeline iteration fetches, updates .txt, deletes completed entry → re-encode Phase 3 only |
| Title unchanged | No action, no re-encode |
| API entry deleted | Ignored locally, no action |
| New video processed | Phase 1 (transcribe) → Phase 2 (AI title) → Upload to API → Phase 3 |
| Video exists in API | Upload skipped, existing title used or updated via sync |
| API down during sync | Warning logged, continues with local state |
| API down during upload | Warning logged, continues pipeline (will retry next run) |

## Testing

### Unit Tests: `tests/test_sr_mp3_manager.py`
- Client URL parsing
- Sync: update different, skip same, ignore missing, fail-safe
- Upload: upload new, skip existing, error handling

**Run:** `uv run python3 -m pytest tests/test_sr_mp3_manager.py -v`

## Deployment

1. **MP3 Manager VPS**: `./remote/deploy.sh root@example.com`
2. **Local package**: `uv pip install -e .`
3. **Set env var**: Add `MP3_MANAGER_URL` to `.env`

## Files Modified

| File | Changes |
|------|---------|
| `pyproject.toml` | Added `packages/sr_mp3_manager` to Hatch packages |
| `src/app/pipeline.py` | Import package, add sync hook at start, add upload hook in Phase 2 |
| `remote/app.py` | Add `/api/files`, `/api/files/<id>` (HEAD), update `/api/upload` to be idempotent |
| `.env.example` | Add `MP3_MANAGER_URL` documentation |

## New Files

| File | Purpose |
|------|---------|
| `packages/sr_mp3_manager/__init__.py` | Package exports |
| `packages/sr_mp3_manager/api.py` | HTTP client |
| `packages/sr_mp3_manager/sync.py` | Title sync logic |
| `packages/sr_mp3_manager/upload.py` | Upload logic |
| `tests/test_sr_mp3_manager.py` | Unit tests |

## Key Design Decisions

1. **One-way sync only** (API → local), deleted API entries ignored
2. **Idempotent uploads** (check existence before uploading)
3. **Fail-safe error handling** (API failures don't stop pipeline)
4. **Single source of truth for Phase 3** (local .txt files)
5. **Exact filename as ID** (includes extension, guaranteed unique)
6. **Full URL in one env var** (simpler configuration)
