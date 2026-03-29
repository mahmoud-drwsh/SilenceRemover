# MP3 Management System

A secure, lightweight Flask application for MP3 file upload, storage, and playback via web interface.

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

### Deploy from Local Machine

Use the deploy script to push code updates to your VPS:

```bash
./deploy.sh <YOUR_SERVER_IP>
```

**Setup SSH key first (one-time):**
```bash
ssh-copy-id root@<YOUR_SERVER_IP>
```

**What the script does:**
- Syncs only changed files (preserves storage/ directory)
- Prints current MP3_TOKEN from server
- Restarts the mp3-manager service
- Verifies deployment health

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
├── app.py              # Main Flask application (full security version)
├── requirements.txt    # Python dependencies
├── Caddyfile          # HTTPS reverse proxy configuration
├── deploy.sh          # SSH deployment script
├── README.md          # This file
├── .gitignore         # Git exclusions
├── storage/           # MP3 files (created on first run)
└── database.db        # SQLite database (created on first run)
```

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
