# Media Manager Implementation Plan

## 1. Architecture Overview

**Single FastAPI backend + Unified SPA with URL-based sections**

- Files organized by **tags** in DB (virtual), never move on disk
- **Flat physical storage**: `/storage/<PROJECT>/audio/` and `/video/`
- **Unified API** with `?type=audio|video` parameter
- **Two sections**: `/#audio` (reviewers) and `/#video` (consumers)

---

## 2. Backend (FastAPI)

### Project Endpoints (5 total)

Base path: `/projects/{token}/{project}/`

```
GET  /projects/{token}/{project}/api/files?type=audio|video&tags=tag1,tag2  - List files
POST /projects/{token}/{project}/api/files                                  - Upload
PUT  /projects/{token}/{project}/api/files/{id}                             - Update tags
DEL  /projects/{token}/{project}/api/files/{id}                             - Delete (trash only)
GET  /projects/{token}/{project}/stream/{id}                                - Stream
```

### Admin Endpoints (2 total)

Base path: `/admin/{admin_token}/`

```
GET  /admin/{admin_token}/api/projects  - List all projects with stats
GET  /admin/{admin_token}/             - Admin dashboard SPA
```

### Database Schema

```sql
CREATE TABLE files (
    id TEXT NOT NULL,           -- filename with extension
    project TEXT NOT NULL,
    type TEXT NOT NULL,         -- 'audio' | 'video'
    title TEXT,
    tags TEXT,                  -- JSON array
    duration INTEGER,
    file_size INTEGER,
    mime_type TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, type, project)  -- Composite key allows same ID in different projects
);
```

---

## 3. Audio Section (`/#audio`)

### Fixed 4 Tabs (bottom)
```
| TODO | READY | ALL | TRASH |
```

### Features
- List audio by tag (click tab to filter)
- Title editing (auto-save)
- Audio player (pauses on section switch)
- Two-way sync with pipeline
- Trash/restore/delete actions

### Workflow
1. Upload with `tags: ["todo"]`
2. Reviewer listens, edits title if needed
3. Reviewer clicks READY tab → adds `tags: ["ready"]`
4. Phase 5 finds ready audio, uploads matching video

### Sync Behavior
- **Two-way sync**: Pipeline ↔ Manager
- Startup: `GET /projects/{token}/{project}/api/files?type=audio`
- Compare API title to local .txt
- Update if different → delete completed marker → trigger re-encode

---

## 4. Video Section (`/#video`)

### Dynamic Tabs (bottom)
```
| FB | TT | all | custom | trash |
```

### URL Behavior
- `/#video` → Default view (all or first tab)
- `/#video?tags=FB` → **Strict isolation**, only FB-tagged videos
- No tab switching when URL specifies tags (isolated view)

### Features
- Tag filter tabs (or strict from URL)
- Video grid/thumbnails
- Player on click
- Download button
- Remove button (removes THIS tag only)
- Custom confirmation modal

### Remove Button Behavior
- Click → confirmation modal: "Remove from FB folder?"
- Confirm → removes "FB" tag from video
- Example: Video has `tags: ["FB", "TT"]` → after confirm: `tags: ["TT"]`
- Video disappears from FB view (no longer tagged FB)

### No Editing
- View only
- No title changes
- No workflow states

---

## 5. Tag System

### Audio Tags (Fixed, Strict)
| Tag | Meaning |
|-----|---------|
| `todo` | Needs review |
| `ready` | Approved |
| `all` | Shows everything (except trash) |
| `trash` | Deleted (soft delete) |

**No custom tags allowed for audio.**

### Video Tags (Freeform)
| Tag | Default | Meaning |
|-----|---------|---------|
| `FB` | ✅ Yes | Facebook |
| `TT` | ✅ Yes | TikTok |
| `all` | - | Shows everything |
| `trash` | - | Deleted |
| *custom* | - | User-created any tag |

**Any custom tags allowed for video.**

### Query Behavior
- No `?tags=` → All files except those with "trash" tag
- `?tags=trash` → Only trashed files
- `?tags=FB,TT` → Files with BOTH tags (AND logic)

---

## 6. Pipeline Integration (5 Phases)

### Phase 3: Audio Upload (Review)
```python
POST /projects/{token}/{project}/api/files
Body: {
    file: <snippet.ogg>,
    id: "video-basename",
    title: "AI Generated Title",
    type: "audio",
    tags: ["todo"]
}
```

### Phase 4: Video Creation (Local Only)
- Creates final video: `output/{sanitized-title}.mp4`
- Does NOT upload yet
- Waits for approval

### Phase 5: Video Delivery (Ready Only)
```python
# 1. Query ready audio files
GET /projects/{token}/{project}/api/files?type=audio&tags=ready

# 2. For each ready audio:
#    - Find matching local video file (by basename/title)
#    - Upload to Media Manager

POST /projects/{token}/{project}/api/files
Body: {
    file: <final.mp4>,
    id: "video-basename",
    title: "Same as audio title",
    type: "video",
    tags: ["FB", "TT"]
}


```

### Startup Sync (Two-Way, Audio Only)
```python
# Before processing any videos
GET /projects/{token}/{project}/api/files?type=audio

# For each audio from API:
# - Compare API title to local title.txt
# - If different: update local .txt with API title
# - Delete completed/{basename}.txt marker
# - Result: Video will be re-encoded with new title on next loop
```

---

## 7. Frontend Structure

### Unified SPA

**Files:**
```
static/
├── index.html              # Shell
├── app.js                  # Main app, hash routing
├── api.js                  # API client (shared)
├── components.js           # Shared components
├── audio-section.js        # Audio-specific UI
├── video-section.js        # Video-specific UI
├── styles.css              # Styles (shared)
└── i18n.js                 # Translations
```

### Routing (URL Hash)

| URL | Section | Behavior |
|-----|---------|----------|
| `/#audio` | Audio | Default audio view |
| `/#audio?tags=todo` | Audio | Filtered to todo |
| `/#video` | Video | Default video view |
| `/#video?tags=FB` | Video | **Strict isolation**, only FB |

### Navigation

**Top:** Audio | Video tabs (switch sections)
**Bottom:** Context-aware tabs
- Audio: TODO | READY | ALL | TRASH (fixed)
- Video: FB | TT | all | custom | trash (dynamic)

### Media Handling
- Audio player pauses when switching to video section
- Video player on click (modal or inline)
- Download button for videos

---

## 8. Physical Storage

```
/var/lib/media-manager/storage/
└── <PROJECT>/
    ├── audio/           # All audio files (flat)
    │   ├── snippet-001.ogg
    │   └── lesson-001.mp3
    └── video/           # All video files (flat)
        ├── final-001.mp4
        └── raw-001.mov
```

**Files never move on disk.** Organization is pure metadata (tags in DB).

---

## 9. Deployment

### Server Location
`/var/lib/media-manager/`

### Files
- `app.py` - FastAPI backend (async)
- `static/` - Frontend SPA
- `storage/` - File storage (audio/, video/)
- `data/database.db` - SQLite
- `requirements.txt` - Python dependencies
- `deploy.sh` - Deploy script
- `media-manager.service` - Systemd service

### Caddy Configuration
```
yourdomain.com {
    handle_path /<TOKEN>/<PROJECT>/* {
        reverse_proxy localhost:8080
    }
}
```

### Deploy Command
```bash
./deploy.sh root@server.com
```

---

## 10. Key Behaviors Summary

| Feature | Audio | Video |
|---------|-------|-------|
| **Bottom tabs** | Fixed 4: todo/ready/all/trash | Dynamic: FB/TT/custom/all/trash |
| **URL isolation** | No (can switch tabs) | Yes (with `?tags=FB`, strict) |
| **Tag creation** | No (fixed 4 only) | Yes (any custom tags) |
| **Title editing** | Yes (auto-save) | No (view only) |
| **Remove button** | Trash (soft delete) | Remove this tag only |
| **Confirmation** | Custom modal | Custom modal |
| **Sync** | Two-way (pipeline ↔ manager) | One-way (pipeline → manager) |
| **Re-encode trigger** | Yes (title change in UI) | No |
| **Upload phase** | Phase 3 (snippet) | Phase 5 (final, ready only) |
| **Default tags** | `[