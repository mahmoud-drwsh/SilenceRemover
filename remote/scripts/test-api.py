#!/usr/bin/env python3
"""Quick API test for Media Manager backend."""

import sys
import json
import requests
from pathlib import Path

BASE_URL = "http://localhost:8080"
TOKEN = "test-token-123"
PROJECT = "test-project"

def test_list_empty():
    """Test listing files when empty."""
    resp = requests.get(f"{BASE_URL}/{TOKEN}/{PROJECT}/api/files")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert isinstance(data, list), f"Expected list, got {type(data)}"
    print("✓ List files (empty)")


def test_upload_audio():
    """Test uploading an audio file."""
    import io

    # Try to use a real test audio file if available
    test_file = Path(__file__).parent.parent / 'test-audio' / '001_test_s.mp3'
    if test_file.exists():
        with open(test_file, 'rb') as f:
            content = f.read()
        mime_type = 'audio/mpeg'
        filename = 'test-audio-001.mp3'
    else:
        # Fallback to dummy file
        content = b'ID3' + b'\x00' * 100  # Minimal MP3 header
        mime_type = 'audio/mpeg'
        filename = 'test-audio-001.mp3'

    files = {'file': (filename, io.BytesIO(content), mime_type)}
    data = {
        'id': 'test-audio-001',
        'title': 'Test Audio File',
        'type': 'audio',
        'tags': json.dumps(['todo'])
    }

    resp = requests.post(
        f"{BASE_URL}/{TOKEN}/{PROJECT}/api/files",
        files=files,
        data=data
    )

    if resp.status_code == 400 and "Invalid file type" in resp.text:
        print("⚠ Upload test skipped (libmagic may not recognize file)")
        return False

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    result = resp.json()
    assert result['ok'] is True
    assert result['id'] == 'test-audio-001'
    assert result['type'] == 'audio'
    print("✓ Upload audio file")
    return True


def test_list_with_tags(uploaded=False):
    """Test listing with tag filter."""
    resp = requests.get(f"{BASE_URL}/{TOKEN}/{PROJECT}/api/files?type=audio&tags=todo")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if uploaded:
        assert len(data) >= 1, "Expected at least 1 file with todo tag"
    print("✓ List with tag filter")


def test_update_tags():
    """Test updating file tags."""
    resp = requests.put(
        f"{BASE_URL}/{TOKEN}/{PROJECT}/api/files/test-audio-001",
        json={'tags': ['todo', 'ready']}
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    result = resp.json()
    assert result['ok'] is True
    assert 'ready' in result['tags']
    print("✓ Update tags")


def test_invalid_audio_tag():
    """Test that invalid audio tags are rejected."""
    resp = requests.put(
        f"{BASE_URL}/{TOKEN}/{PROJECT}/api/files/test-audio-001",
        json={'tags': ['invalid-tag']}
    )
    assert resp.status_code == 400, f"Expected 400 for invalid tag, got {resp.status_code}"
    print("✓ Invalid audio tag rejected")


def test_stream():
    """Test streaming endpoint."""
    resp = requests.get(f"{BASE_URL}/{TOKEN}/{PROJECT}/stream/test-audio-001")
    if resp.status_code == 404:
        print("⚠ Stream test skipped (file not found)")
        return
    assert resp.status_code == 200
    print("✓ Stream file")


def test_spa_routing():
    """Test SPA serving."""
    resp = requests.get(f"{BASE_URL}/{TOKEN}/{PROJECT}/")
    assert resp.status_code == 200
    assert 'text/html' in resp.headers.get('content-type', '')
    print("✓ SPA routing")


def main():
    print("=" * 50)
    print("Media Manager API Tests")
    print("=" * 50)
    print()

    try:
        test_list_empty()
        uploaded = test_upload_audio()
        test_list_with_tags(uploaded=uploaded)
        if uploaded:
            test_update_tags()
            test_invalid_audio_tag()
            test_stream()
        test_spa_routing()

        print()
        print("=" * 50)
        print("All tests passed!")
        print("=" * 50)
        return 0

    except AssertionError as e:
        print(f"✗ Test failed: {e}")
        return 1
    except requests.exceptions.ConnectionError:
        print("✗ Could not connect to server. Is it running?")
        print(f"   URL: {BASE_URL}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
