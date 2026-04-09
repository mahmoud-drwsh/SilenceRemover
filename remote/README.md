# MP3 Management System

A secure, lightweight Flask application for MP3 file upload, storage, and playback via web interface.

## User Stories

### As an authenticated user...

1. **Audio File List View**
   - I want to see the list of playable audio files that were uploaded to my project
   - So that I can browse and manage my audio content

2. **Audio Metadata Display**
   - I want to see their titles and their IDs in small subtext
   - So that I can easily identify and reference specific audio files

3. **Audio Playback Controls**
   - I want to play and pause the audio with a single responsive button
   - So that I can quickly preview audio without complex controls

4. **Publishing Status Indicator**
   - I want to mark an audio file ready for publishing to have a visual indicator of what's ready and what's not
   - So that I can track which files are approved for release

5. **Compact Mobile-First UI**
   - I want a compact mobile-friendly interface with bottom navigation and expandable cards
   - So that I can easily manage audio files on small screens without excessive scrolling

6. **Safe Delete (Trash)**
   - I want to move audio files to a "trash" state instead of immediate deletion
   - So that I can recover accidentally deleted files, with the backend clearing trash manually after a safety period

7. **Compact Audio Progress Bar**
   - I want a small progress bar that doesn't take much space
   - So that I can see the current playback position without cluttering the interface

8. **Audio Seeking**
   - I want to click or drag on the progress bar to jump to any position in the audio
   - So that I can quickly navigate to specific parts of the audio without listening from the beginning

9. **Currently Playing Indicator**
   - I want to see which audio file is currently playing in the list
   - So that I know which title I'm editing while listening

10. **Audio Duration Display**
   - I want to see the total duration of each audio file in the list
   - So that I know how long each clip is before I play it

11. **Auto-save Title Edits**
   - I want title changes to save automatically as I type (with debounce)
   - So that I don't lose my edits or need to click a save button

### As a developer...

1. **Audio Upload API (API-only)**
   - I want an API endpoint to upload audio files to a specific project URL and associate each with an ID
   - So that I can programmatically manage uploads (web interface is view/play/edit only, no upload)

2. **Minimal List API**
   - I want an API endpoint that returns the complete list of files for a specific project ID as IDs and their titles only
   - So that I can quickly fetch a lightweight inventory for a specific project without unnecessary metadata or cross-project data

3. **Project-Based URL Structure**
   - I want to set a project ID so that each project has a dedicated base URL to access its list
   - So that I can organize and isolate different audio collections (e.g., `https://domain.com/TOKEN/PROJECT_ID/`)

---

### As any user (authenticated or developer)...

1. **URL Path Token Authentication**
   - I want URL path token based auth for all operations including upload, viewing, and management
   - So that I can access all functionality through a single secure URL pattern without additional login steps

2. **Project Isolation**
   - I want someone with the link for project A to not be able to navigate within the UI to project B
   - So that projects remain separated and organized, with no cross-project access from within the interface

12. **Bottom Navigation Views**
   - I want navigation tabs at the bottom of the screen for TODO, Ready, All, and Trash views
   - So that I can quickly switch views with my thumb without reaching to the top of the screen

13. **Expandable Card UI**
   - I want file cards that expand when clicked to reveal full controls (progress bar, edit title, action buttons)
   - So that the list stays compact but I can access detailed controls when needed

14. **TODO-First Default View**
   - I want the interface to default to showing TODO (not ready) files first
   - So that I immediately see what work needs my attention

15. **Ready Files View**
   - I want a dedicated view to see only files marked as "ready for publishing"
   - So that I can quickly access the curated content approved for release

16. **Trash View**
   - I want a dedicated view to see deleted (trashed) files with restore option
   - So that I can review and potentially recover accidentally deleted content

---

## Features

- **Secure Access**: URL-based token authentication via environment variable
- **File Security**: Files stored with hashed names for obfuscation
- **Web Interface**: Single-page application with auto-saving title editing (800ms debounce)
- **SQLite Database**: Lightweight, file-based storage
- **HTTPS Support**: Automatic SSL certificates via Caddy
- **Audit Logging**: Security event tracking

## Quick Start

### Local Development

1. **Install dependencies:**
```bash
pip install -r requirements.txt
```

2. **Set the token environment variable:**
```bash
export MP3_TOKEN=$(openssl rand -hex 32)
echo "Your token: $MP3_TOKEN"
```

3. **Run the application:**
```bash
python app.py
```

4. **Access the interface:**
```
http://localhost:8080/interface/$MP3_TOKEN
```

## Production Deployment

### Prerequisites
- VPS with SSH access
- Domain or IP pointing to VPS
- SSH key configured (passwordless login)

### One-Time VPS Setup

1. **Install Caddy on your VPS:**
```bash
apt-get install -y caddy
```

2. **Configure Caddy** (edit `/etc/caddy/Caddyfile` with your domain):
```
your-domain.com {
    reverse_proxy localhost:8080
    
    header {
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        X-XSS-Protection "1; mode=block"
    }
}
```

3. **Start Caddy:**
```bash
systemctl start caddy
systemctl enable caddy
```

### Deploy to Server

```bash
# Sync files (preserves storage/ and *.db on server)
rsync -avz --delete --exclude='.git' --exclude='storage/' --exclude='*.db' --exclude='*.log' --exclude='__pycache__/' --exclude='*.pyc' --exclude='.env' --exclude='venv/' ./ root@<SERVER_IP>:/var/lib/mp3-manager/
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/upload/<token>` | POST | Upload MP3 (form: id, title, file) |
| `/interface/<token>` | GET | Web interface |
| `/data/<token>` | GET | JSON list of all songs |
| `/update/<token>` | PATCH | Update title (JSON: id, title) |
| `/stream/<token>/<file>` | GET | Stream MP3 file |

## Usage Examples

### Upload via cURL (HTTPS)

```bash
curl -X POST https://your-domain.com/upload/YOUR_TOKEN \
  -F "id=202603281530" \
  -F "title=My Awesome Song" \
  -F "file=@/path/to/song.mp3"
```

### Get Data (JSON)

```bash
curl https://your-domain.com/data/YOUR_TOKEN
```

### Update Title

```bash
curl -X PATCH https://your-domain.com/update/YOUR_TOKEN \
  -H "Content-Type: application/json" \
  -d '{"id": "202603281530", "title": "New Title"}'
```

### Access Web Interface

Open browser to:
```
https://your-domain.com/interface/YOUR_TOKEN
```

## File Structure

```
remote/
├── requirements.txt    # Python dependencies
├── Caddyfile          # HTTPS reverse proxy configuration
├── translations.json   # EN/AR UI translations
├── README.md          # This file
├── .gitignore         # Git exclusions
└── static/            # Frontend SPA
    ├── index.html
    ├── app.js
    ├── components.js
    ├── api.js
    ├── styles.css
    └── i18n.js
```

**VPS-only (not in git):** `app.py`, `storage/`, `database.db`

## Security Features

- **Environment-based token**: No hardcoded secrets
- **Non-root execution**: App runs as dedicated user
- **Rate limiting**: 100 requests/hour per IP
- **File type validation**: Magic number checking (not just extension)
- **Path traversal protection**: Validated file paths
- **Input sanitization**: XSS and injection prevention
- **Audit logging**: Security events logged
- **Automatic security headers**: HSTS, CSP, X-Frame-Options

## Management Commands

**On the VPS:**

```bash
# Check service status
systemctl status mp3-manager

# View logs
journalctl -u mp3-manager -f

# Restart service
systemctl restart mp3-manager

# View security audit log
tail -f /root/mp3-manager/security.log

# Backup database and files
tar -czf backup-$(date +%Y%m%d).tar.gz /root/mp3-manager/database.db /root/mp3-manager/storage/
```

## Troubleshooting

### Service won't start
```bash
# Check for errors
journalctl -u mp3-manager -n 50 --no-pager

# Verify token is set
echo $MP3_TOKEN

# Check file permissions
ls -la /root/mp3-manager/
```

### Can't connect via SSH
```bash
# Test SSH connection
ssh root@YOUR_SERVER_IP "echo OK"

# If fails, set up SSH key
ssh-copy-id root@YOUR_SERVER_IP
```

### Files not syncing
- Check that `rsync` is installed locally
- Verify SSH key is configured
- Ensure VPS IP is correct

## Environment Variables

Set these on your VPS (in systemd service or .env file):

- `MP3_TOKEN` - Authentication token (generate with `openssl rand -hex 32`)
- `FLASK_ENV=production` - Production mode

## License

[Your License]

---

**Note**: This is the production-ready secure version. For a single VPS deployment with automatic HTTPS and one-command updates via SSH.
