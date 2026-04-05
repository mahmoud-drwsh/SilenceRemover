#!/usr/bin/env python3
"""
HTMX-based MP3 Manager
Separated: Python backend + HTML templates
Supports: English (en) and Arabic (ar) - LTR layout enforced
"""

import os
import sqlite3
import uuid
import json
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string, send_file, make_response
try:
    from markupsafe import Markup
except ImportError:
    from flask import Markup
from mutagen.mp3 import MP3

# Config
TOKEN = os.environ.get('MP3_TOKEN', str(uuid.uuid4()))
UPLOAD_DIR = '/var/www/uploads'
DB_PATH = '/var/lib/mp3-manager/db.sqlite'
PORT = 8080

# Flask setup
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key')

# Load templates
TEMPLATES_DIR = Path(__file__).parent / 'templates'

# Load translations
TRANSLATIONS_PATH = Path(__file__).parent / 'translations.json'
TRANSLATIONS = json.loads(TRANSLATIONS_PATH.read_text())

def get_text(key, lang='en'):
    """Get translated text for key, fallback to English"""
    return TRANSLATIONS.get(lang, TRANSLATIONS['en']).get(key, TRANSLATIONS['en'][key])

def load_template(name):
    """Load template file as string"""
    return (TEMPLATES_DIR / name).read_text()

BASE_TEMPLATE = load_template('base.html')
CARD_TEMPLATE = load_template('card.html')

# Initialize
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR, exist_ok=True)

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
            trashed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def format_duration(seconds):
    if not seconds:
        return "0:00"
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}:{secs:02d}"

def render_card(file, token, project, view, lang='en'):
    """Render a single card using the card template"""
    return Markup(render_template_string(CARD_TEMPLATE, 
                                   file=file, token=token, 
                                   project=project, view=view, 
                                   lang=lang, t=lambda k: get_text(k, lang)))

# Routes

@app.route('/<token>/<project>/')
def index(token, project):
    if token != TOKEN:
        return "Invalid token", 403
    
    view = request.args.get('view', 'notready')
    lang = request.args.get('lang', 'en')
    if lang not in TRANSLATIONS:
        lang = 'en'
    
    conn = sqlite3.connect(DB_PATH)
    if view == 'trash':
        cursor = conn.execute('SELECT id, title, filename, duration, ready FROM files WHERE project = ? AND trashed = 1 ORDER BY created_at DESC', (project,))
    elif view == 'ready':
        cursor = conn.execute('SELECT id, title, filename, duration, ready FROM files WHERE project = ? AND trashed = 0 AND ready = 1 ORDER BY created_at DESC', (project,))
    elif view == 'notready':
        cursor = conn.execute('SELECT id, title, filename, duration, ready FROM files WHERE project = ? AND trashed = 0 AND ready = 0 ORDER BY created_at DESC', (project,))
    else:
        cursor = conn.execute('SELECT id, title, filename, duration, ready FROM files WHERE project = ? AND trashed = 0 ORDER BY created_at DESC', (project,))
    
    files = []
    for row in cursor.fetchall():
        files.append({
            'id': row[0], 'title': row[1], 'filename': row[2],
            'duration': row[3], 'duration_formatted': format_duration(row[3]),
            'ready': row[4]
        })
    conn.close()
    
    # Translated view names
    view_names = {
        'notready': f"⏳ {get_text('todo', lang)}", 
        'ready': f"✓ {get_text('ready', lang)}", 
        'all': f"📁 {get_text('all', lang)}", 
        'trash': f"🗑 {get_text('trash', lang)}"
    }
    
    # If HTMX request, only return the file list
    if request.headers.get('HX-Request'):
        return Markup(''.join(render_card(f, token, project, view, lang) for f in files))
    
    # Helper for template that captures token/project/view/lang
    def card_for_template(file):
        return render_card(file, token, project, view, lang)
    
    return render_template_string(BASE_TEMPLATE,
                                  token=token, project=project,
                                  view=view, view_name=view_names.get(view, 'Files'),
                                  files=files, lang=lang, 
                                  t=lambda k: get_text(k, lang),
                                  card=card_for_template)

@app.route('/<token>/<project>/toggle-ready/<file_id>', methods=['GET', 'POST'])
def toggle_ready(token, project, file_id):
    if token != TOKEN:
        if request.headers.get('HX-Request'):
            return "Invalid token", 403
        return jsonify({"error": "Invalid token"}), 403 if request.method == 'POST' else ("Invalid token", 403)
    
    conn = sqlite3.connect(DB_PATH)
    
    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form
        new_ready = 1 if data.get('ready') in [True, 'true', 1, '1'] else 0
        conn.execute('UPDATE files SET ready = ? WHERE id = ? AND project = ?', (new_ready, file_id, project))
        conn.commit()
        conn.close()
        
        # For HTMX requests: return empty to trigger delete, or re-render card
        if request.headers.get('HX-Request'):
            # If in TODO view and now ready, delete from view
            view = request.args.get('view', 'notready')
            lang = request.args.get('lang', 'en')
            if view == 'notready' and new_ready:
                return "", 200  # Empty = delete card from DOM
            # Otherwise re-render the card
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.execute('SELECT id, title, filename, duration, ready FROM files WHERE id = ?', (file_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                file = {'id': row[0], 'title': row[1], 'filename': row[2],
                        'duration': row[3], 'duration_formatted': format_duration(row[3]),
                        'ready': row[4]}
                return Markup(render_card(file, token, project, view, lang))
            return "", 404
        
        return jsonify({"success": True, "ready": bool(new_ready)})
    else:
        # GET request - traditional browser
        cursor = conn.execute('SELECT ready FROM files WHERE id = ? AND project = ?', (file_id, project))
        row = cursor.fetchone()
        if row:
            new_ready = 0 if row[0] else 1
            conn.execute('UPDATE files SET ready = ? WHERE id = ? AND project = ?', (new_ready, file_id, project))
            conn.commit()
        conn.close()
        view = request.args.get('view', 'notready')
        return f'<script>window.location.href="/{token}/{project}/?view={view}"</script>'

@app.route('/<token>/<project>/trash/<file_id>', methods=['GET', 'POST'])
def trash_file(token, project, file_id):
    if token != TOKEN:
        return jsonify({"error": "Invalid token"}), 403 if request.method == 'POST' else ("Invalid token", 403)
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute('UPDATE files SET trashed = 1 WHERE id = ? AND project = ?', (file_id, project))
    conn.commit()
    conn.close()
    
    if request.method == 'POST':
        return jsonify({"success": True})
    else:
        view = request.args.get('view', 'notready')
        return f'<script>window.location.href="/{token}/{project}/?view={view}"</script>'

@app.route('/<token>/<project>/restore/<file_id>', methods=['GET', 'POST'])
def restore_file(token, project, file_id):
    if token != TOKEN:
        return jsonify({"error": "Invalid token"}), 403 if request.method == 'POST' else ("Invalid token", 403)
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute('UPDATE files SET trashed = 0 WHERE id = ? AND project = ?', (file_id, project))
    conn.commit()
    conn.close()
    
    if request.method == 'POST':
        return jsonify({"success": True})
    else:
        return f'<script>window.location.href="/{token}/{project}/?view=trash"</script>'

@app.route('/<token>/<project>/delete/<file_id>', methods=['GET', 'POST'])
def delete_permanent(token, project, file_id):
    if token != TOKEN:
        return jsonify({"error": "Invalid token"}), 403 if request.method == 'POST' else ("Invalid token", 403)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute('SELECT filename FROM files WHERE id = ? AND project = ? AND trashed = 1', (file_id, project))
    row = cursor.fetchone()
    
    if row:
        filepath = os.path.join(UPLOAD_DIR, row[0])
        if os.path.exists(filepath):
            os.remove(filepath)
        conn.execute('DELETE FROM files WHERE id = ? AND project = ?', (file_id, project))
        conn.commit()
    
    conn.close()
    
    if request.method == 'POST':
        return jsonify({"success": True})
    else:
        return f'<script>window.location.href="/{token}/{project}/?view=trash"</script>'

@app.route('/<token>/<project>/update/<file_id>', methods=['POST'])
def update(token, project, file_id):
    if token != TOKEN:
        return "Invalid token", 403
    
    title = request.form.get('title', '')
    conn = sqlite3.connect(DB_PATH)
    conn.execute('UPDATE files SET title = ? WHERE id = ? AND project = ?', (title, file_id, project))
    conn.commit()
    
    cursor = conn.execute('SELECT id, title, filename, duration, ready FROM files WHERE id = ?', (file_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return "", 404
    
    file = {'id': row[0], 'title': row[1], 'filename': row[2],
            'duration': row[3], 'duration_formatted': format_duration(row[3]),
            'ready': row[4]}
    
    view = request.args.get('view', 'notready')
    lang = request.args.get('lang', 'en')
    return Markup(render_card(file, token, project, view, lang))

@app.route('/<token>/<project>/stream/<file_id>')
def stream(token, project, file_id):
    if token != TOKEN:
        return "Invalid token", 403
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute('SELECT filename FROM files WHERE id = ? AND project = ? AND trashed = 0', (file_id, project))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return "Not found", 404
    
    filepath = os.path.join(UPLOAD_DIR, row[0])
    if not os.path.exists(filepath):
        return "File not found", 404
    
    return send_file(filepath, mimetype='audio/mpeg')

@app.route('/<token>/<project>/api/upload', methods=['POST'])
def api_upload(token, project):
    """Idempotent upload endpoint for pipeline."""
    if token != TOKEN:
        return jsonify({"error": "Invalid token"}), 403
    
    file_id = request.form.get('id')
    title = request.form.get('title', '')
    file = request.files.get('file') or request.files.get('audio')
    
    if not file_id:
        return jsonify({"error": "Missing id"}), 400
    
    conn = sqlite3.connect(DB_PATH)
    
    # Check if already exists (idempotent)
    cursor = conn.execute(
        'SELECT id FROM files WHERE id = ? AND project = ?',
        (file_id, project)
    )
    exists = cursor.fetchone() is not None
    
    if exists:
        # Just update title, no need to re-upload audio
        conn.execute(
            'UPDATE files SET title = ? WHERE id = ? AND project = ?',
            (title, file_id, project)
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True, "id": file_id, "updated": True})
    
    # New upload - require file
    if not file:
        conn.close()
        return jsonify({"error": "Missing file"}), 400
    
    ext = file.filename.rsplit('.', 1)[-1].lower()
    filename = f"{file_id}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    
    file.save(filepath)
    
    try:
        audio = MP3(filepath)
        duration = int(audio.info.length)
    except:
        duration = 0
    
    conn.execute(
        'INSERT INTO files (id, project, title, filename, duration, ready) VALUES (?, ?, ?, ?, ?, ?)',
        (file_id, project, title, filename, duration, 0)
    )
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "id": file_id, "created": True}), 201

@app.route('/favicon.ico')
def favicon():
    return '', 204


# API endpoints for pipeline integration
@app.route('/<token>/<project>/api/files')
def api_get_files(token, project):
    """Return all files with titles for pipeline sync."""
    if token != TOKEN:
        return jsonify({"error": "Invalid token"}), 403
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        'SELECT id, title, ready, trashed FROM files WHERE project = ?',
        (project,)
    )
    files = [
        {
            "id": row[0],
            "title": row[1] or '',
            "ready": bool(row[2]),
            "trashed": bool(row[3])
        }
        for row in cursor.fetchall()
    ]
    conn.close()
    return jsonify(files)


@app.route('/<token>/<project>/api/files/<file_id>', methods=['HEAD'])
def api_check_file(token, project, file_id):
    """Check if file exists (for idempotent upload check)."""
    if token != TOKEN:
        return '', 403
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        'SELECT 1 FROM files WHERE id = ? AND project = ?',
        (file_id, project)
    )
    exists = cursor.fetchone() is not None
    conn.close()
    
    return '', 200 if exists else 404


@app.after_request
def add_header(response):
    response.cache_control.no_store = True
    return response

if __name__ == '__main__':
    print(f"Token: {TOKEN}")
    print(f"Starting on port {PORT}")
    app.run(host='127.0.0.1', port=PORT, debug=False)
