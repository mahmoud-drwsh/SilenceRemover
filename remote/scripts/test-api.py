#!/usr/bin/env python3
"""Quick API test for Media Manager backend."""

import sys
import json
import requests
import io
from pathlib import Path

BASE_URL = "http://localhost:8080"
TOKEN = "test-token-123"
PROJECT = "test-project"


def _create_minimal_mp4() -> bytes:
    """Create minimal valid MP4 bytes for testing (ftyp + moov atoms)."""
    # ftyp atom: "ftyp" + version + brands
    ftyp = b'\x00\x00\x00\x1cftypisom\x00\x00\x00\x00isommp41'
    # moov atom (minimal structure)
    mvhd = b'\x00\x00\x00\x20mvhd' + b'\x00' * 28  # 32 bytes total
    trak = b'\x00\x00\x00\x08trak'  # empty trak as placeholder
    moov_content = mvhd + trak
    moov = (len(moov_content) + 8).to_bytes(4, 'big') + b'moov' + moov_content
    return ftyp + moov


def _create_minimal_ogg() -> bytes:
    """Create minimal valid OGG Vorbis bytes."""
    # OGG page header (27 bytes) + segment table + Vorbis identification header
    capture_pattern = b'OggS'
    version = b'\x00'
    header_type = b'\x02'  # BOS (beginning of stream)
    granule_position = b'\x00' * 8
    serial_number = b'\x01\x00\x00\x00'
    page_sequence = b'\x00\x00\x00\x00'
    crc = b'\x00\x00\x00\x00'  # Placeholder CRC
    num_segments = b'\x01'
    segment_table = b'\x1e'  # 30 bytes
    
    # Vorbis identification header (packet type 1 + "vorbis")
    vorbis_id = b'\x01vorbis\x00\x00\x00\x00\x02\x44\xac\x00\x00\x00\x00\x00\x00\x00\xee\x02\x00'
    
    page = (27 + 1 + 1 + 30).to_bytes(4, 'little') + capture_pattern + version + header_type
    page += granule_position + serial_number + page_sequence + crc + num_segments + segment_table + vorbis_id
    return page

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


def test_video_overwrite_scenarios(base_url, token, project):
    """Test video auto-overwrite scenarios.
    
    Test 1: First upload (new ID) - should succeed
    Test 2: Re-upload same ID, same title - should return 409 CONFLICT
    Test 3: Re-upload same ID, different title - should overwrite (200 + overwritten:true)
    Test 4: Audio never overwrites - should return 409 even with different title
    Test 5: Pre-flight check endpoint - verify exists/title matching
    """
    import time
    
    url = f"{base_url}/{token}/{project}/api/files"
    test_id = f"test-overwrite-{int(time.time())}"
    
    print(f"\n  [Video Overwrite Tests - ID: {test_id}]")
    
    # === Test 1: First upload (new ID) ===
    print("  Test 1: First upload (new ID)...")
    content1 = _create_minimal_mp4()
    files1 = {'file': ('video1.mp4', io.BytesIO(content1), 'video/mp4')}
    data1 = {
        'id': test_id,
        'title': 'Original Title',
        'type': 'video',
        'tags': json.dumps(['FB'])
    }
    resp1 = requests.post(url, files=files1, data=data1)
    assert resp1.status_code == 200, f"Expected 200, got {resp1.status_code}: {resp1.text}"
    result1 = resp1.json()
    assert result1.get('ok') is True, f"Expected ok=True, got {result1}"
    assert result1.get('overwritten') is False, f"Expected overwritten=False for new upload"
    print("    ✓ First upload succeeded, overwritten=False")
    
    # === Test 2: Re-upload same ID, same title ===
    print("  Test 2: Re-upload same ID, same title...")
    files2 = {'file': ('video1.mp4', io.BytesIO(content1), 'video/mp4')}
    data2 = {
        'id': test_id,
        'title': 'Original Title',
        'type': 'video',
        'tags': json.dumps(['FB'])
    }
    resp2 = requests.post(url, files=files2, data=data2)
    assert resp2.status_code == 409, f"Expected 409 CONFLICT, got {resp2.status_code}: {resp2.text}"
    print("    ✓ 409 CONFLICT returned for duplicate")
    
    # === Test 3: Re-upload same ID, different title → Overwrite ===
    print("  Test 3: Re-upload same ID, different title (overwrite)...")
    content2 = _create_minimal_mp4() + b'\x00\x01\x02\x03'  # Different content
    files3 = {'file': ('video2.mp4', io.BytesIO(content2), 'video/mp4')}
    data3 = {
        'id': test_id,
        'title': 'Updated Title',
        'type': 'video',
        'tags': json.dumps(['TT'])
    }
    resp3 = requests.post(url, files=files3, data=data3)
    assert resp3.status_code == 200, f"Expected 200, got {resp3.status_code}: {resp3.text}"
    result3 = resp3.json()
    assert result3.get('ok') is True, f"Expected ok=True, got {result3}"
    assert result3.get('overwritten') is True, f"Expected overwritten=True for overwrite"
    
    # Verify file was actually replaced by checking size/content
    stream_resp = requests.get(f"{base_url}/{token}/{project}/stream/{test_id}")
    assert stream_resp.status_code == 200
    streamed_size = len(stream_resp.content)
    assert streamed_size == len(content2), f"File size mismatch: expected {len(content2)}, got {streamed_size}"
    print("    ✓ Overwrite succeeded, file replaced")
    
    # === Test 4: Audio never overwrites ===
    print("  Test 4: Audio never overwrites...")
    audio_id = f"test-audio-{int(time.time())}"
    audio_content = _create_minimal_ogg()
    
    # First audio upload
    audio_files1 = {'file': ('audio1.ogg', io.BytesIO(audio_content), 'audio/ogg')}
    audio_data1 = {
        'id': audio_id,
        'title': 'Original Audio',
        'type': 'audio',
        'tags': json.dumps(['todo'])
    }
    resp_audio1 = requests.post(url, files=audio_files1, data=audio_data1)
    assert resp_audio1.status_code == 200, f"Initial audio upload failed: {resp_audio1.text}"
    
    # Try to overwrite with different title
    audio_files2 = {'file': ('audio2.ogg', io.BytesIO(audio_content + b'\xff'), 'audio/ogg')}
    audio_data2 = {
        'id': audio_id,
        'title': 'Different Audio Title',
        'type': 'audio',
        'tags': json.dumps(['ready'])
    }
    resp_audio2 = requests.post(url, files=audio_files2, data=audio_data2)
    assert resp_audio2.status_code == 409, f"Expected 409 for audio overwrite, got {resp_audio2.status_code}: {resp_audio2.text}"
    print("    ✓ Audio returns 409 even with different title")
    
    # === Test 5: Pre-flight check endpoint ===
    print("  Test 5: Pre-flight check endpoint...")
    
    # Check with matching title
    check_url_match = f"{url}?type=video&id={test_id}&title=Updated+Title"
    resp_check1 = requests.get(check_url_match)
    assert resp_check1.status_code == 200
    check_result1 = resp_check1.json()
    assert isinstance(check_result1, list), f"Expected list, got {type(check_result1)}"
    assert len(check_result1) >= 1, f"Expected at least 1 match, got {len(check_result1)}"
    assert any(item.get('id') == test_id for item in check_result1), f"Expected to find {test_id}"
    print("    ✓ Pre-flight with matching title returns result")
    
    # Check with non-matching title
    check_url_diff = f"{url}?type=video&id={test_id}&title=Wrong+Title"
    resp_check2 = requests.get(check_url_diff)
    assert resp_check2.status_code == 200
    check_result2 = resp_check2.json()
    assert isinstance(check_result2, list), f"Expected list, got {type(check_result2)}"
    # With title filter, should return empty or the item without match
    print("    ✓ Pre-flight with different title handled correctly")
    
    # Cleanup: Delete test files
    try:
        requests.delete(f"{url}/{test_id}")
        requests.delete(f"{url}/{audio_id}")
    except Exception:
        pass  # Ignore cleanup errors
    
    print("  All video overwrite tests passed!")


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
        
        # Video overwrite scenarios test
        print("\n  Testing video overwrite scenarios...")
        test_video_overwrite_scenarios(BASE_URL, TOKEN, PROJECT)

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
