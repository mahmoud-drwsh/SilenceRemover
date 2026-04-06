"""
MP3 Manager - API-only backend
Serves JSON API for static SPA frontend
"""

import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename
from mutagen.mp3 import MP3

# Config from environment
TOKEN = os.environ.get('MP3_TOKEN', str(uuid.uuid4()))
UPLOAD_DIR = os.environ.get('UPLOAD_DIR', '/var/www/uploads')
DB_PATH = os.environ.get('DB_PATH', '/var/lib/mp3-manager/db.sqlite')
STATIC_DIR = os.environ.get('STATIC_DIR', '/var/lib/mp3-manager/static')
PORT = int(os.environ.get('PORT', 8080))

# Ensure directories exist
Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='/static')
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key')

# Initialize database
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            title TEXT,
            filename TEXT NOT NULL,
            duration INTEGER DEFAULT 0,
            ready INTEGER DEFAULT 0,
            trashed INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()


def require_token(token):
    """Verify token matches."""
    if token != TOKEN:
        return False
    return True


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# API Endpoints

@app.route('/<token>/<project>/api/files')
def api_get_files(token, project):
    """Get all files for a project."""
    if not require_token(token):
        return jsonify({"error": "Invalid token"}), 403
    
    conn = get_db()
    cursor = conn.execute(
        'SELECT id, title, filename, duration, ready, trashed FROM files WHERE project = ?',
        (project,)
    )
    files = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    # Convert integers to booleans
    for f in files:
        f['ready'] = bool(f['ready'])
        f['trashed'] = bool(f['trashed'])
    
    return jsonify(files)


@app.route('/<token>/<project>/api/update/<file_id>', methods=['POST'])
def api_update(token, project, file_id):
    """Update file title."""
    if not require_token(token):
        return jsonify({"error": "Invalid token"}), 403
    
    title = request.form.get('title', '')
    
    conn = get_db()
    conn.execute(
        'UPDATE files SET title = ? WHERE id = ? AND project = ?',
        (title, file_id, project)
    )
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "id": file_id})


@app.route('/<token>/<project>/api/toggle-ready/<file_id>', methods=['POST'])
def api_toggle_ready(token, project, file_id):
    """Toggle ready status."""
    if not require_token(token):
        return jsonify({"error": "Invalid token"}), 403
    
    data = request.get_json() or {}
    ready = 1 if data.get('ready') else 0
    
    conn = get_db()
    conn.execute(
        'UPDATE files SET ready = ? WHERE id = ? AND project = ?',
        (ready, file_id, project)
    )
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "id": file_id, "ready": bool(ready)})


@app.route('/<token>/<project>/api/trash/<file_id>', methods=['POST'])
def api_trash(token, project, file_id):
    """Move file to trash."""
    if not require_token(token):
        return jsonify({"error": "Invalid token"}), 403
    
    conn = get_db()
    conn.execute(
        'UPDATE files SET trashed = 1 WHERE id = ? AND project = ?',
        (file_id, project)
    )
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "id": file_id})


@app.route('/<token>/<project>/api/restore/<file_id>', methods=['POST'])
def api_restore(token, project, file_id):
    """Restore file from trash."""
    if not require_token(token):
        return jsonify({"error": "Invalid token"}), 403
    
    conn = get_db()
    conn.execute(
        'UPDATE files SET trashed = 0 WHERE id = ? AND project = ?',
        (file_id, project)
    )
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "id": file_id})


@app.route('/<token>/<project>/api/delete/<file_id>', methods=['POST'])
def api_delete(token, project, file_id):
    """Permanently delete file."""
    if not require_token(token):
        return jsonify({"error": "Invalid token"}), 403
    
    conn = get_db()
    
    # Get filename to delete from filesystem
    cursor = conn.execute(
        'SELECT filename FROM files WHERE id = ? AND project = ? AND trashed = 1',
        (file_id, project)
    )
    row = cursor.fetchone()
    
    if row:
        filepath = os.path.join(UPLOAD_DIR, row['filename'])
        if os.path.exists(filepath):
            os.remove(filepath)
        
        conn.execute('DELETE FROM files WHERE id = ? AND project = ?', (file_id, project))
        conn.commit()
    
    conn.close()
    
    return jsonify({"success": True, "id": file_id})


@app.route('/<token>/<project>/api/upload', methods=['POST'])
def api_upload(token, project):
    """Upload audio file."""
    if not require_token(token):
        return jsonify({"error": "Invalid token"}), 403
    
    file_id = request.form.get('id')
    title = request.form.get('title', '')
    file = request.files.get('file') or request.files.get('audio')
    
    if not file_id:
        return jsonify({"error": "Missing id"}), 400
    
    conn = get_db()
    
    # Check if exists
    cursor = conn.execute(
        'SELECT id FROM files WHERE id = ? AND project = ?',
        (file_id, project)
    )
    exists = cursor.fetchone() is not None
    
    if exists:
        # Update title only
        conn.execute(
            'UPDATE files SET title = ? WHERE id = ? AND project = ?',
            (title, file_id, project)
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True, "id": file_id, "updated": True})
    
    # New upload
    if not file:
        conn.close()
        return jsonify({"error": "Missing file"}), 400
    
    # Save file
    ext = Path(file.filename).suffix.lower() or '.ogg'
    filename = f"{file_id}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    file.save(filepath)
    
    # Get duration
    try:
        audio = MP3(filepath)
        duration = int(audio.info.length)
    except:
        duration = 0
    
    # Insert record
    conn.execute(
        'INSERT INTO files (id, project, title, filename, duration, ready, trashed) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (file_id, project, title, filename, duration, 0, 0)
    )
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "id": file_id, "created": True}), 201


@app.route('/<token>/<project>/stream/<file_id>')
def api_stream(token, project, file_id):
    """Stream audio file."""
    if not require_token(token):
        return jsonify({"error": "Invalid token"}), 403
    
    conn = get_db()
    cursor = conn.execute(
        'SELECT filename FROM files WHERE id = ? AND project = ?',
        (file_id, project)
    )
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"error": "File not found"}), 404
    
    filepath = os.path.join(UPLOAD_DIR, row['filename'])
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    
    return send_file(filepath, mimetype='audio/mpeg')


@app.route('/<token>/<project>/monitor')
def api_monitor(token, project):
    """Simple HTTPS endpoint for monitoring access attempts."""
    if not require_token(token):
        return jsonify({"error": "Invalid token"}), 403
    
    # Get attack statistics
    stats = {
        "timestamp": datetime.now().isoformat(),
        "server": project,
        "attacks": {
            "ssh_failed_24h": 0,
            "ufw_blocks_24h": 0,
            "banned_ips": [],
            "top_attackers": []
        },
        "access": {
            "your_ip": request.remote_addr,
            "last_ssh_logins": []
        }
    }
    
    # Get banned IPs from fail2ban
    try:
        import subprocess
        result = subprocess.run(['fail2ban-client', 'status', 'sshd'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'Banned IP list' in line:
                    ips = line.split(':')[-1].strip()
                    if ips:
                        stats["attacks"]["banned_ips"] = [ip.strip() for ip in ips.split(',')]
                if 'Currently banned' in line:
                    count = line.split(':')[-1].strip()
                    stats["attacks"]["currently_banned_count"] = count
    except:
        pass
    
    # Get SSH auth stats from journalctl
    try:
        result = subprocess.run(
            ['journalctl', '-u', 'ssh', '--since', '24 hours ago', '-q'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            failed = result.stdout.count('Failed password') + result.stdout.count('Invalid user')
            accepted = result.stdout.count('Accepted publickey')
            stats["attacks"]["ssh_failed_24h"] = failed
            stats["access"]["successful_ssh_24h"] = accepted
    except:
        pass
    
    # Get UFW blocks
    try:
        result = subprocess.run(
            ['dmesg'], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            blocks = result.stdout.count('[UFW BLOCK]')
            stats["attacks"]["ufw_blocks_24h"] = blocks
    except:
        pass
    
    # Get last 5 SSH logins
    try:
        result = subprocess.run(['last', '-5'], capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            logins = []
            for line in result.stdout.strip().split('\n')[:5]:
                if 'pts' in line or 'tty' in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        logins.append({
                            "user": parts[0],
                            "ip": parts[2],
                            "time": " ".join(parts[3:6]) if len(parts) > 5 else ""
                        })
            stats["access"]["last_ssh_logins"] = logins
    except:
        pass
    
    return jsonify(stats)


# HTML Monitor Interface - Token Protected
MONITOR_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Server Security Monitor</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #1a1a2e;
      color: #fff;
      padding: 20px;
      min-height: 100vh;
    }
    h1 { font-size: 24px; margin-bottom: 20px; color: #00d4aa; }
    .status { display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 20px; }
    .card { background: #16213e; border-radius: 12px; padding: 15px; min-width: 140px; flex: 1; }
    .card h3 { font-size: 12px; color: #8892b0; text-transform: uppercase; margin-bottom: 8px; }
    .card .number { font-size: 32px; font-weight: bold; color: #00d4aa; }
    .card .number.danger { color: #ff6b6b; }
    .card .number.warning { color: #ffd93d; }
    .section { background: #16213e; border-radius: 12px; padding: 15px; margin-bottom: 15px; }
    .section h2 { font-size: 16px; color: #00d4aa; margin-bottom: 12px; }
    .ip-list { display: flex; flex-wrap: wrap; gap: 8px; }
    .ip-badge { background: #ff6b6b; color: #fff; padding: 6px 12px; border-radius: 20px; font-size: 13px; font-family: monospace; }
    .login-item { background: #0f3460; padding: 10px; border-radius: 8px; margin-bottom: 8px; display: flex; justify-content: space-between; }
    .login-item .ip { color: #00d4aa; font-family: monospace; }
    .last-update { text-align: center; color: #8892b0; font-size: 12px; margin-top: 20px; }
  </style>
</head>
<body>
  <h1>🔒 Server Security Monitor</h1>
  <div class="status">
    <div class="card"><h3>SSH Attacks (24h)</h3><div class="number" id="sshFailed">-</div></div>
    <div class="card"><h3>Blocked (24h)</h3><div class="number" id="ufwBlocks">-</div></div>
    <div class="card"><h3>Banned IPs</h3><div class="number" id="bannedCount">-</div></div>
    <div class="card"><h3>Your Logins</h3><div class="number" id="successLogins">-</div></div>
  </div>
  <div class="section">
    <h2>🚫 Banned Attacker IPs</h2>
    <div class="ip-list" id="bannedIps"><span style="color: #8892b0;">Loading...</span></div>
  </div>
  <div class="section">
    <h2>✅ Your Recent SSH Logins</h2>
    <div id="loginHistory"><span style="color: #8892b0;">Loading...</span></div>
  </div>
  <div class="last-update">Last updated: <span id="lastUpdate">-</span></div>
  <script>
    async function fetchData() {
      try {
        const response = await fetch(window.location.pathname.replace('/view', ''));
        if (!response.ok) throw new Error('Failed to fetch');
        const data = await response.json();
        updateUI(data);
      } catch (err) {
        document.body.innerHTML = '<div style="background:#ff6b6b;padding:15px;border-radius:8px;">Error: ' + err.message + '</div>';
      }
    }
    function updateUI(data) {
      document.getElementById('sshFailed').textContent = data.attacks?.ssh_failed_24h || 0;
      document.getElementById('ufwBlocks').textContent = data.attacks?.ufw_blocks_24h || 0;
      document.getElementById('bannedCount').textContent = data.attacks?.currently_banned_count || '0';
      document.getElementById('successLogins').textContent = data.access?.successful_ssh_24h || 0;
      const bannedIps = data.attacks?.banned_ips || [];
      document.getElementById('bannedIps').innerHTML = bannedIps.length > 0 ? bannedIps.map(ip => `<span class="ip-badge">${ip}</span>`).join('') : '<span style="color: #8892b0;">No banned IPs</span>';
      const logins = data.access?.last_ssh_logins || [];
      document.getElementById('loginHistory').innerHTML = logins.length > 0 ? logins.map(login => `<div class="login-item"><span>${login.user} @ ${login.time}</span><span class="ip">${login.ip}</span></div>`).join('') : '<span style="color: #8892b0;">No recent logins</span>';
      document.getElementById('lastUpdate').textContent = new Date().toLocaleString();
    }
    fetchData();
    setInterval(fetchData, 10000);
  </script>
</body>
</html>'''


@app.route('/<token>/<project>/monitor/view')
def api_monitor_view(token, project):
    """Serve monitor HTML interface - token protected."""
    if not require_token(token):
        return jsonify({"error": "Invalid token"}), 403
    return MONITOR_HTML


@app.route('/<token>/', defaults={'path': ''})
@app.route('/<token>/<project>/')
@app.route('/<token>/<project>/<path:path>')
def serve_spa(token=None, project=None, path=None):
    """Serve the static SPA for all non-API routes."""
    # Verify token if provided in path
    if token and not require_token(token):
        return jsonify({"error": "Invalid token"}), 403
    
    # Serve index.html for the SPA
    return send_file(os.path.join(STATIC_DIR, 'index.html'))


@app.after_request
def add_header(response):
    response.cache_control.no_store = True
    return response


if __name__ == '__main__':
    print(f"Token: {TOKEN}")
    print(f"Static dir: {STATIC_DIR}")
    print(f"Starting on port {PORT}")
    app.run(host='127.0.0.1', port=PORT, debug=False)
