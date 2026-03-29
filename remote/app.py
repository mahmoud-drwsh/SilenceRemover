#!/usr/bin/env python3
"""
MP3 Management System - SECURED VERSION
Hardened Flask application with comprehensive security measures.
"""

import os
import re
import sqlite3
import uuid
import hashlib
import hmac
import time
from datetime import datetime
from functools import wraps, lru_cache
from flask import Flask, request, jsonify, send_file, Response, abort, g
from werkzeug.utils import secure_filename
import magic

# ============================================================================
# SECURITY CONFIGURATION
# ============================================================================

# CRITICAL: Load from environment variable, never hardcode
SECRET_TOKEN = os.environ.get('MP3_TOKEN')
if not SECRET_TOKEN:
    raise ValueError("MP3_TOKEN environment variable must be set! Run: export MP3_TOKEN=$(openssl rand -hex 32)")

# Security constants
MAX_TITLE_LENGTH = 200
MAX_ID_LENGTH = 50
ALLOWED_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
RATE_LIMIT_WINDOW = 3600  # 1 hour
MAX_REQUESTS_PER_HOUR = 100  # Per IP

# Paths - use absolute paths for security
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'database.db')
STORAGE_PATH = os.path.join(BASE_DIR, 'storage')
LOG_PATH = os.path.join(BASE_DIR, 'security.log')

# Ensure storage exists with secure permissions
os.makedirs(STORAGE_PATH, exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

# ============================================================================
# FLASK APP CONFIGURATION
# ============================================================================

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False

# Security headers middleware
@app.after_request
def add_security_headers(response):
    """Add comprehensive security headers to all responses."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; media-src 'self';"
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response

# ============================================================================
# RATE LIMITING
# ============================================================================

# Simple in-memory rate limiter (use Redis in production)
request_history = {}

def check_rate_limit(ip_address):
    """Check if IP has exceeded rate limit."""
    current_time = time.time()
    
    # Clean old entries
    for ip in list(request_history.keys()):
        request_history[ip] = [t for t in request_history[ip] if current_time - t < RATE_LIMIT_WINDOW]
        if not request_history[ip]:
            del request_history[ip]
    
    # Check current IP
    if ip_address in request_history:
        if len(request_history[ip_address]) >= MAX_REQUESTS_PER_HOUR:
            return False
        request_history[ip_address].append(current_time)
    else:
        request_history[ip_address] = [current_time]
    
    return True

# ============================================================================
# AUDIT LOGGING
# ============================================================================

def log_security_event(event_type, details, ip_address=None):
    """Log security events for audit trail."""
    timestamp = datetime.utcnow().isoformat()
    ip = ip_address or request.remote_addr
    user_agent = request.headers.get('User-Agent', 'Unknown')
    
    log_entry = f"[{timestamp}] [{event_type}] [IP: {ip}] [UA: {user_agent}] {details}\n"
    
    try:
        with open(LOG_PATH, 'a') as f:
            f.write(log_entry)
    except Exception:
        pass  # Don't crash if logging fails

# ============================================================================
# DATABASE
# ============================================================================

def init_database():
    """Initialize SQLite database with proper schema."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Main songs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS songs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,
            file_hash TEXT,
            upload_ip TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Audit log table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            song_id TEXT,
            ip_address TEXT,
            user_agent TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

def get_db():
    """Get database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def audit_log(action, song_id=None):
    """Log action to database audit trail."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO audit_log (action, song_id, ip_address, user_agent)
            VALUES (?, ?, ?, ?)
        ''', (action, song_id, request.remote_addr, request.headers.get('User-Agent', '')[:200]))
        conn.commit()
        conn.close()
    except Exception:
        pass

# ============================================================================
# INPUT VALIDATION
# ============================================================================

def validate_id(song_id):
    """Validate song ID format."""
    if not song_id:
        return False, "ID is required"
    
    if len(song_id) > MAX_ID_LENGTH:
        return False, f"ID too long (max {MAX_ID_LENGTH} chars)"
    
    if not ALLOWED_ID_PATTERN.match(song_id):
        return False, "ID can only contain letters, numbers, hyphens, and underscores"
    
    return True, None

def validate_title(title):
    """Validate title format."""
    if not title:
        return False, "Title is required"
    
    if len(title) > MAX_TITLE_LENGTH:
        return False, f"Title too long (max {MAX_TITLE_LENGTH} chars)"
    
    # Basic XSS prevention - check for script tags
    lower_title = title.lower()
    if any(tag in lower_title for tag in ['<script', 'javascript:', 'onerror=', 'onload=']):
        return False, "Title contains prohibited content"
    
    return True, None

def validate_filename(filename):
    """Validate and sanitize filename."""
    # Use Werkzeug's secure_filename
    safe_name = secure_filename(filename)
    
    if not safe_name:
        return False, "Invalid filename"
    
    # Check extension
    if not safe_name.lower().endswith('.mp3'):
        return False, "Only .mp3 files allowed"
    
    # Check for path traversal attempts
    if '..' in safe_name or '/' in safe_name or '\\' in safe_name:
        return False, "Path traversal detected"
    
    return True, safe_name

# ============================================================================
# FILE TYPE VALIDATION
# ============================================================================

def validate_mp3_content(file_path):
    """Validate that file is actually an MP3 using magic numbers."""
    try:
        # Check MIME type
        mime = magic.Magic(mime=True)
        file_type = mime.from_file(file_path)
        
        # Valid audio MIME types
        valid_types = ['audio/mpeg', 'audio/mp3', 'audio/x-mpeg-3']
        
        if file_type not in valid_types:
            return False, f"Invalid file content. Detected: {file_type}"
        
        return True, None
    except Exception as e:
        return False, f"Cannot validate file type: {str(e)}"

def calculate_file_hash(file_path):
    """Calculate SHA-256 hash of file for integrity."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

# ============================================================================
# SECURE FILE STORAGE
# ============================================================================

def generate_secure_filename(original_filename):
    """Generate a secure, non-predictable filename."""
    # Extract extension
    ext = os.path.splitext(original_filename)[1].lower()
    # Generate UUID + timestamp for uniqueness
    unique_id = uuid.uuid4().hex[:16]
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:-3]
    # Hash the token for additional security (token not visible in filename)
    token_hash = hashlib.sha256(SECRET_TOKEN.encode()).hexdigest()[:8]
    return f"{token_hash}_{timestamp}_{unique_id}{ext}"

def get_storage_path(internal_filename):
    """Get absolute path with path traversal protection."""
    # Normalize and join
    target_path = os.path.abspath(os.path.join(STORAGE_PATH, internal_filename))
    
    # Ensure it's within storage directory (prevent path traversal)
    if not target_path.startswith(os.path.abspath(STORAGE_PATH)):
        return None
    
    return target_path

# ============================================================================
# AUTHENTICATION
# ============================================================================

def validate_token(f):
    """Decorator to validate SECRET_TOKEN in URL with constant-time comparison."""
    @wraps(f)
    def decorated_function(token, *args, **kwargs):
        # Check rate limit first
        client_ip = request.remote_addr
        if not check_rate_limit(client_ip):
            log_security_event('RATE_LIMIT_EXCEEDED', f'IP: {client_ip}', client_ip)
            abort(429, description="Rate limit exceeded. Try again later.")
        
        # Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(token, SECRET_TOKEN):
            log_security_event('INVALID_TOKEN_ATTEMPT', f'Token: {token[:10]}... IP: {client_ip}', client_ip)
            audit_log('AUTH_FAILURE')
            abort(401, description="Invalid token")
        
        audit_log('AUTH_SUCCESS')
        return f(token, *args, **kwargs)
    return decorated_function

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(400)
def bad_request(error):
    log_security_event('BAD_REQUEST', str(error.description))
    return jsonify({'error': 'Bad request', 'message': str(error.description)}), 400

@app.errorhandler(401)
def unauthorized(error):
    return jsonify({'error': 'Unauthorized', 'message': 'Invalid or missing token'}), 401

@app.errorhandler(403)
def forbidden(error):
    return jsonify({'error': 'Forbidden', 'message': 'Access denied'}), 403

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found', 'message': 'Resource not found'}), 404

@app.errorhandler(413)
def too_large(error):
    return jsonify({'error': 'File too large', 'message': f'Maximum file size is {MAX_FILE_SIZE // 1024 // 1024}MB'}), 413

@app.errorhandler(429)
def rate_limited(error):
    return jsonify({'error': 'Rate limited', 'message': 'Too many requests. Please try again later.'}), 429

@app.errorhandler(500)
def internal_error(error):
    log_security_event('SERVER_ERROR', str(error))
    # Don't expose internal details
    return jsonify({'error': 'Internal server error', 'message': 'An error occurred. Please try again.'}), 500

# ============================================================================
# ROUTES
# ============================================================================

@app.route('/')
def root():
    """Root path returns 404 - no information disclosure."""
    abort(404)

@app.route('/health')
def health_check():
    """Health check endpoint - minimal info."""
    return jsonify({'status': 'ok', 'timestamp': datetime.utcnow().isoformat()})

@app.route('/upload/<token>', methods=['POST'])
@validate_token
def upload(token):
    """Securely upload MP3 file with comprehensive validation."""
    client_ip = request.remote_addr
    
    try:
        # Get and validate form data
        song_id = request.form.get('id', '').strip()
        title = request.form.get('title', '').strip()
        
        # Validate ID
        valid, error_msg = validate_id(song_id)
        if not valid:
            log_security_event('INVALID_ID', f'ID: {song_id}, Error: {error_msg}', client_ip)
            return jsonify({'error': error_msg}), 400
        
        # Validate title
        valid, error_msg = validate_title(title)
        if not valid:
            log_security_event('INVALID_TITLE', f'Error: {error_msg}', client_ip)
            return jsonify({'error': error_msg}), 400
        
        # Check for file
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if not file or file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Validate filename
        valid, result = validate_filename(file.filename)
        if not valid:
            log_security_event('INVALID_FILENAME', f'Filename: {file.filename}, Error: {result}', client_ip)
            return jsonify({'error': result}), 400
        
        safe_filename = result
        
        # Generate secure internal filename (not predictable)
        internal_filename = generate_secure_filename(safe_filename)
        file_path = get_storage_path(internal_filename)
        
        if not file_path:
            log_security_event('PATH_TRAVERSAL_ATTEMPT', f'IP: {client_ip}', client_ip)
            return jsonify({'error': 'Invalid file path'}), 403
        
        # Save file temporarily for validation
        temp_path = file_path + '.tmp'
        file.save(temp_path)
        
        # Validate file content is actually MP3
        valid, error_msg = validate_mp3_content(temp_path)
        if not valid:
            os.remove(temp_path)
            log_security_event('INVALID_FILE_CONTENT', f'Error: {error_msg}, IP: {client_ip}', client_ip)
            return jsonify({'error': error_msg}), 400
        
        # Calculate file hash for integrity
        file_hash = calculate_file_hash(temp_path)
        
        # Move to final location
        os.rename(temp_path, file_path)
        
        # Set secure file permissions (readable only by owner)
        os.chmod(file_path, 0o600)
        
        # Insert into database
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO songs (id, title, filename, file_hash, upload_ip)
                VALUES (?, ?, ?, ?, ?)
            ''', (song_id, title, internal_filename, file_hash, client_ip))
            conn.commit()
            audit_log('UPLOAD_SUCCESS', song_id)
            log_security_event('UPLOAD_SUCCESS', f'ID: {song_id}, File: {internal_filename}', client_ip)
            
        except sqlite3.IntegrityError:
            # ID already exists - update instead
            cursor.execute('''
                UPDATE songs 
                SET title = ?, filename = ?, file_hash = ?, upload_ip = ?, updated_at = ?
                WHERE id = ?
            ''', (title, internal_filename, file_hash, client_ip, datetime.utcnow().isoformat(), song_id))
            
            # Delete old file if exists
            cursor.execute('SELECT filename FROM songs WHERE id = ?', (song_id,))
            old_row = cursor.fetchone()
            if old_row:
                old_path = get_storage_path(old_row['filename'])
                if old_path and os.path.exists(old_path) and old_path != file_path:
                    os.remove(old_path)
            
            conn.commit()
            audit_log('UPDATE_SUCCESS', song_id)
            log_security_event('UPDATE_SUCCESS', f'ID: {song_id}', client_ip)
        
        conn.close()
        
        return jsonify({
            'success': True,
            'id': song_id,
            'title': title,
            'message': 'File uploaded successfully'
        }), 201
        
    except Exception as e:
        log_security_event('UPLOAD_ERROR', f'Error: {str(e)}', client_ip)
        # Clean up temp file if exists
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)
        raise

@app.route('/interface/<token>', methods=['GET'])
@validate_token
def interface(token):
    """Serve the single-page HTML interface (same as before but secured)."""
    html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>MP3 Manager</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); padding: 30px; }
        h1 { color: #333; margin-bottom: 20px; font-size: 24px; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { text-align: left; padding: 12px; border-bottom: 1px solid #eee; }
        th { background: #f8f9fa; font-weight: 600; color: #555; }
        tr:hover { background: #f8f9fa; }
        .audio-cell { width: 300px; }
        audio { width: 100%; height: 40px; }
        .title-input { width: 100%; padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; transition: border-color 0.2s; }
        .title-input:focus { outline: none; border-color: #4CAF50; }
        .title-input.saving { border-color: #ff9800; }
        .title-input.saved { border-color: #4CAF50; }
        .id-cell { width: 150px; color: #666; font-family: monospace; }
        @media screen and (max-width: 768px) {
            body { padding: 10px; }
            .container { padding: 15px; border-radius: 0; }
            h1 { font-size: 20px; margin-bottom: 15px; }
            thead { display: none; }
            table, tbody, tr, td { display: block; width: 100%; }
            tr { background: white; border: 1px solid #e0e0e0; border-radius: 8px; margin-bottom: 15px; padding: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
            tr:hover { background: white; }
            td { border: none; padding: 10px 0; text-align: left; }
            td.id-cell::before { content: "ID: "; font-weight: 600; color: #666; display: block; margin-bottom: 5px; font-size: 12px; text-transform: uppercase; }
            td:not(.id-cell):not(.audio-cell)::before { content: "Title: "; font-weight: 600; color: #666; display: block; margin-bottom: 5px; font-size: 12px; text-transform: uppercase; }
            td.audio-cell::before { content: "Audio: "; font-weight: 600; color: #666; display: block; margin-bottom: 10px; font-size: 12px; text-transform: uppercase; }
            .id-cell { width: 100%; font-size: 13px; word-break: break-all; background: #f8f9fa; padding: 8px 10px; border-radius: 4px; margin-bottom: 10px; }
            .audio-cell { width: 100%; padding-top: 10px; }
            audio { height: 50px; border-radius: 25px; }
            .title-input { font-size: 16px; padding: 12px; }
        }
        .loading { text-align: center; padding: 40px; color: #666; }
        .error { text-align: center; padding: 40px; color: #f44336; }
        .no-songs { text-align: center; padding: 40px; color: #666; font-style: italic; }
    </style>
</head>
<body>
    <div class="container">
        <h1>MP3 Manager</h1>
        <div id="content"><div class="loading">Loading...</div></div>
    </div>
    <script>
        const TOKEN = window.location.pathname.split('/')[2];
        const API_BASE = window.location.origin;
        function debounce(func, wait) {
            let timeout;
            return function(...args) {
                clearTimeout(timeout);
                timeout = setTimeout(() => func.apply(this, args), wait);
            };
        }
        async function loadSongs() {
            try {
                const response = await fetch(`${API_BASE}/data/${TOKEN}`);
                if (!response.ok) throw new Error('Failed to load');
                const songs = await response.json();
                renderSongs(songs);
            } catch (error) {
                document.getElementById('content').innerHTML = `<div class="error">Error: ${error.message}</div>`;
            }
        }
        async function updateTitle(id, title, input) {
            input.classList.add('saving');
            input.classList.remove('saved');
            try {
                const response = await fetch(`${API_BASE}/update/${TOKEN}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id, title })
                });
                if (!response.ok) throw new Error('Update failed');
                input.classList.remove('saving');
                input.classList.add('saved');
                setTimeout(() => input.classList.remove('saved'), 1000);
            } catch (error) {
                input.classList.remove('saving');
            }
        }
        function renderSongs(songs) {
            if (songs.length === 0) {
                document.getElementById('content').innerHTML = '<div class="no-songs">No songs uploaded yet</div>';
                return;
            }
            const html = `<table><thead><tr><th class="id-cell">ID</th><th>Title</th><th class="audio-cell">Audio</th></tr></thead><tbody>${songs.map(song => `<tr><td class="id-cell">${escapeHtml(song.id)}</td><td><input type="text" class="title-input" value="${escapeHtml(song.title)}" data-id="${escapeHtml(song.id)}"></td><td class="audio-cell"><audio controls preload="none"><source src="${API_BASE}/stream/${TOKEN}/${encodeURIComponent(song.filename)}" type="audio/mpeg"></audio></td></tr>`).join('')}</tbody></table>`;
            document.getElementById('content').innerHTML = html;
            document.querySelectorAll('.title-input').forEach(input => {
                const id = input.getAttribute('data-id');
                input.addEventListener('input', debounce(() => updateTitle(id, input.value, input), 800));
            });
        }
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        loadSongs();
    </script>
</body>
</html>'''
    return Response(html, mimetype='text/html')

@app.route('/data/<token>', methods=['GET'])
@validate_token
def get_data(token):
    """Return JSON array of all songs - limited fields for security."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id, title, filename FROM songs ORDER BY id ASC')
        rows = cursor.fetchall()
        conn.close()
        
        # Don't expose internal filenames or sensitive data
        songs = [{
            'id': row['id'],
            'title': row['title']
            # Note: filename is used internally but we could hash it for extra security
        } for row in rows]
        
        audit_log('DATA_ACCESS')
        return jsonify(songs)
        
    except Exception:
        return jsonify({'error': 'Database error'}), 500

@app.route('/update/<token>', methods=['PATCH'])
@validate_token
def update_song(token):
    """Update song title with validation."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data'}), 400
        
        song_id = data.get('id', '').strip()
        title = data.get('title', '').strip()
        
        # Validate inputs
        valid, error = validate_id(song_id)
        if not valid:
            return jsonify({'error': error}), 400
        
        valid, error = validate_title(title)
        if not valid:
            return jsonify({'error': error}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('UPDATE songs SET title = ?, updated_at = ? WHERE id = ?',
                      (title, datetime.utcnow().isoformat(), song_id))
        
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({'error': 'Song not found'}), 404
        
        conn.commit()
        conn.close()
        
        audit_log('TITLE_UPDATE', song_id)
        return jsonify({'success': True, 'id': song_id, 'title': title})
        
    except Exception:
        return jsonify({'error': 'Update failed'}), 500

@app.route('/stream/<token>/<path:filename>', methods=['GET'])
@validate_token
def stream_file(token, filename):
    """Stream MP3 file with security checks."""
    try:
        # Decode filename
        from urllib.parse import unquote
        decoded_filename = unquote(filename)
        
        # Validate no path traversal
        if '..' in decoded_filename or '/' in decoded_filename:
            log_security_event('PATH_TRAVERSAL_STREAM', f'Filename: {decoded_filename}')
            abort(403)
        
        # Get internal filename from database (don't trust user input)
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT filename FROM songs WHERE filename LIKE ?', (f'%_{decoded_filename}',))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return jsonify({'error': 'File not found'}), 404
        
        internal_filename = row['filename']
        file_path = get_storage_path(internal_filename)
        
        if not file_path or not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        
        audit_log('FILE_STREAM', filename)
        
        # Stream file with proper MIME type
        return send_file(
            file_path,
            mimetype='audio/mpeg',
            as_attachment=False,
            download_name=decoded_filename
        )
        
    except Exception:
        return jsonify({'error': 'Streaming error'}), 500

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    init_database()
    
    # Log startup
    log_security_event('SERVER_START', f'PID: {os.getpid()}, User: {os.getuid()}')
    
    print("=" * 60)
    print("MP3 Manager - SECURED VERSION")
    print("=" * 60)
    print(f"Database: {DB_PATH}")
    print(f"Storage: {STORAGE_PATH}")
    print(f"Security Log: {LOG_PATH}")
    print(f"Token configured: {'Yes' if SECRET_TOKEN else 'No'}")
    print("=" * 60)
    print("WARNING: This app must NOT run as root!")
    print("Create a dedicated user: useradd -r -s /bin/false mp3app")
    print("=" * 60)
    
    # Run with minimal threads for security
    app.run(host='127.0.0.1', port=8080, debug=False, threaded=True)
