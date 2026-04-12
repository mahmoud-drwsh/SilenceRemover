# Media Manager

A secure, lightweight FastAPI application for audio and video file management with tag-based organization. Built for the SilenceRemover pipeline 5-phase workflow.

## Features

- **Audio & Video Support**: MP3, MP4, WAV, OGG, FLAC, AAC, MOV, AVI, MKV, WebM
- **Project-Based Organization**: Each project isolated with token-based access
- **Tag-Based Organization**: Virtual folders via JSON tags (no file moving)
- **Secure Access**: URL-based token authentication
- **Web Interface**: Single-page application with inline audio player and title editing
- **SQLite Database**: Lightweight with JSON tag storage
- **HTTPS Support**: Automatic SSL certificates via Caddy
- **Auto-Start**: systemd service for production

## Quick Start

### Local Development

```bash
./scripts/local.sh
```

Access: `http://localhost:8080/$MEDIA_TOKEN/test-project/`

### Deploy to VPS

```bash
./deploy.sh root@myserver.com
```

Outputs your token and URLs automatically.

## File Structure

```
remote/
├── app.py                   # FastAPI backend
├── deploy.sh                # Deploy to VPS
├── media-manager.service    # systemd service
├── requirements.txt         # Python dependencies
├── Caddyfile               # HTTPS configuration
├── README.md               # This file
├── .gitignore              # Git exclusions
├── scripts/                # Helper scripts
│   ├── local.sh            # Run locally (dev server)
│   ├── start.sh            # Start manually on VPS
│   ├── migrate_db.py       # Database migration (old → new schema)
│   ├── migrate_project_storage.py  # Migrate flat → project-prefixed storage
│   ├── test_migration.py   # Test migration script
│   ├── install-service.sh  # Install systemd service
│   ├── test-api.sh         # API test suite (bash)
│   ├── test-api.py         # API test suite (Python)
│   ├── list-db.sh          # View database
│   └── generate-test-media.sh  # Create test files
└── static/                 # Frontend SPA
    └── index.html          # Self-contained SPA (all-in-one)
```

**VPS storage structure (project-prefixed):**
```
/var/lib/media-manager/
├── .env                    # Token (auto-generated)
├── database.db             # SQLite database
├── storage/                # File storage
│   ├── audio/              # Audio files by project
│   │   ├── {project}/
│   │   │   └── {id}.ogg
│   │   └── ...
│   └── video/              # Video files by project
│       ├── {project}/
│       │   └── {id}.mp4
│       └── ...
└── venv/                   # Python environment
```

Projects are isolated both in the database (via `project` column) and on disk (via subdirectory). This allows the same file ID to exist in different projects without collision.

## Query Parameters for GET /api/files

| Parameter | Type | Description |
|-----------|------|-------------|
| `type` | `audio` \| `video` | Filter by file type |
| `tags` | comma-separated | AND logic - files must have ALL specified tags |
| `sort` | `asc` (default) \| `desc` | Sort order by ID |
| `check_id` | string | Pre-flight: check if specific ID exists |
| `check_title` | string | Pre-flight: compare title (requires `check_id`) |

**Pre-flight check example:**
```bash
# Check if audio exists and compare titles (returns would_overwrite flag)
curl "https://your-domain.com/$TOKEN/ihya/api/files?type=audio&check_id=lesson-001&check_title=New Title"
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/<token>/<project>/api/files?type=audio\|video&tags=...` | GET | List files (optional filters) |
| `/<token>/<project>/api/files` | POST | Upload audio/video |
| `/<token>/<project>/api/files/<id>?type=audio\|video` | PUT | Update file tags/title (**type required**) |
| `/<token>/<project>/api/files/<id>?type=audio\|video` | DELETE | Delete file permanently (**type required**) |
| `/<token>/<project>/stream/<id>?type=audio\|video` | GET | Stream file (**type required**) |

## Migration from Old (Flask) Schema

If you have an existing database from the Flask version (with `ready`/`trashed` columns), migrate before deploying:

```bash
# On the server (after deploying code but before starting service)
cd /var/lib/media-manager

# 1. Backup old database
cp /var/lib/mp3-manager/db.sqlite /var/lib/mp3-manager/db.sqlite.backup.$(date +%Y%m%d)

# 2. Run migration (copies and converts)
python3 scripts/migrate_db.py /var/lib/mp3-manager/db.sqlite /var/lib/media-manager/database.db

# 3. Verify migration output shows correct tag distribution
# 4. Start service
sudo systemctl start media-manager
```

**What the migration does:**
- Copies old DB to new location
- Converts `ready=1` → `tags: ["ready"]`
- Converts `trashed=1` → `tags: ["trash"]`
- Converts default → `tags: ["todo"]`
- Leaves source database untouched

## Production Setup

### Prerequisites

- VPS with SSH access
- Domain pointing to VPS
- SSH key configured

### One-Time VPS Setup

```bash
# Install Caddy (for HTTPS)
apt-get install -y caddy

# Configure Caddy
nano /etc/caddy/Caddyfile
# Add:
# your-domain.com {
#     handle_path /static/* {
#         root * /var/lib/media-manager/static
#         file_server
#         header Cache-Control "public, max-age=86400"
#     }
#     handle_path /api/* {
#         reverse_proxy localhost:8080
#     }
#     handle_path /stream/* {
#         reverse_proxy localhost:8080
#     }
#     reverse_proxy localhost:8080
# }

systemctl start caddy
systemctl enable caddy
```

**Note:** The Media Manager uses token-prefixed paths (`/{token}/{project}/api/...`). The fallback `reverse_proxy` directive handles all routes—specific `/api/*` and `/stream/*` handlers in this example are optional since the FastAPI app validates tokens internally.

### Deploy and Start

```bash
# From local machine
./deploy.sh root@your-domain.com
```

This will:
1. Sync files to `/var/lib/media-manager/`
2. Install systemd service
3. Start the service
4. Print your token

### Service Commands

```bash
# On VPS
sudo systemctl status media-manager    # Check status
sudo systemctl restart media-manager   # Restart
sudo journalctl -u media-manager -f    # View logs

# Get token
cat /var/lib/media-manager/.env
```

## Testing

```bash
# Generate test audio/video files
./scripts/generate-test-media.sh 5

# Run API tests
./scripts/test-api.sh
# or
python3 scripts/test-api.py

# Test migration
python3 scripts/test_migration.py

# View database
./scripts/list-db.sh
```

## Environment Variables

- `MEDIA_TOKEN` - Authentication token (auto-generated on first run)
- `DATA_DIR` - Data directory (default: `/var/lib/media-manager`)
- `PROJECT_NAME` - Default project name (default: 'default')

## Tag-Based Workflow

The Media Manager uses **tags** for virtual folder organization:

### Audio Tags (Fixed Set)
- `todo` - Waiting for review (TODO folder)
- `ready` - Approved, ready for video delivery (Ready folder)
- `all` - Default tag for all audio
- `trash` - Deleted items (Trash folder)

### Video Tags (Freeform)
- `FB` - Facebook folder
- `TT` - TikTok folder
- `trash` - Trash folder
- Any custom tags

**Example Flow:**
1. Pipeline uploads audio with `tags: ["todo"]` (appears in TODO)
2. Editor reviews, edits title, clicks "Ready" → `tags: ["ready"]` (moves to Ready)
3. Pipeline sees ready audio, creates video, uploads with `tags: ["FB", "TT"]`
4. Video appears in both FB and TT folders

## Upload Examples

```bash
# Upload audio (Phase 3)
curl -X POST https://your-domain.com/$TOKEN/ihya/api/files \
  -F "id=video-basename" \
  -F "title=The AI Generated Title" \
  -F "type=audio" \
  -F "tags=[\"todo\"]" \
  -F "file=@snippet.ogg"

# Upload video (Phase 5)
curl -X POST https://your-domain.com/$TOKEN/ihya/api/files \
  -F "id=video-basename" \
  -F "title=The AI Generated Title" \
  -F "type=video" \
  -F "tags=[\"FB\", \"TT\"]" \
  -F "file=@output.mp4"

# Mark audio as ready (type parameter is required)
curl -X PUT "https://your-domain.com/$TOKEN/ihya/api/files/video-basename?type=audio" \
  -H "Content-Type: application/json" \
  -d '{"tags": ["ready"]}'

# List ready audio
curl "https://your-domain.com/$TOKEN/ihya/api/files?type=audio&tags=ready"

# List all files
curl "https://your-domain.com/$TOKEN/ihya/api/files"
```

## SilenceRemover Integration

Set `MEDIA_MANAGER_URL` in your SilenceRemover `.env`:

```bash
MEDIA_MANAGER_URL=https://your-domain.com/TOKEN/ihya/
```

This enables:
- **Phase 3**: Auto-upload audio with `tags: ["todo"]`
- **Phase 5**: Upload video only when audio has `tags: ["ready"]`
- **Two-way sync**: Fetch edited titles from Media Manager at startup

## Supported File Types

**Audio:** MP3, MP4 (audio), WAV, OGG, FLAC, AAC, M4A  
**Video:** MP4, M4V, WebM, OGV, MOV, AVI, MKV

Maximum file size: 500MB

## Migration from Old Service

If upgrading from the old Flask-based `mp3-manager`:

1. **Stop old service:**
   ```bash
   sudo systemctl stop mp3-manager
   sudo systemctl disable mp3-manager
   ```

2. **Deploy new code:**
   ```bash
   ./deploy.sh root@your-server
   ```

3. **Migrate database:**
   ```bash
   sudo python3 /var/lib/media-manager/scripts/migrate_db.py \
     /var/lib/mp3-manager/db.sqlite \
     /var/lib/media-manager/database.db
   ```

4. **Start new service:**
   ```bash
   sudo systemctl start media-manager
   ```

5. **Verify:**
   ```bash
   curl http://localhost:8080/$TOKEN/ihya/api/files
   ```

## Migration to Project-Prefixed Storage

If you have files in the old flat structure (pre-project subdirectories):

```bash
# 1. Check what would be migrated (dry run)
python3 scripts/migrate_project_storage.py

# 2. Backup and migrate
python3 scripts/migrate_project_storage.py --execute

# 3. Verify files are accessible
./scripts/test-api.sh
```

The app supports **dual-path mode** during migration:
- **New uploads** go to `storage/{type}/{project}/`
- **Existing files** are found in either location (old or new)
- **Zero downtime** - service works during migration
