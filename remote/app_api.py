"""
MP3 Manager - API-only backend
Serves JSON API for static SPA frontend
"""

import os
import sqlite3
import uuid
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


# Serve static SPA for all other routes
@app.route('/', defaults={'path': ''})
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
