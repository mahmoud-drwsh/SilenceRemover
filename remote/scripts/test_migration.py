#!/usr/bin/env python3
"""Test the database migration script."""

import sqlite3
import tempfile
from pathlib import Path
import sys

# Add remote/scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from migrate_db import migrate_database


def test_migration():
    """Test full migration flow."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Create old schema database
        source = tmpdir / 'old_db.sqlite'
        conn = sqlite3.connect(source)
        conn.executescript('''
            CREATE TABLE files (
                id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                file_type TEXT NOT NULL,
                title TEXT,
                filename TEXT NOT NULL,
                duration INTEGER DEFAULT 0,
                ready INTEGER DEFAULT 0,
                trashed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        
        # Insert test data
        test_data = [
            ('file1', 'test', 'audio', 'Ready Audio', 'file1.ogg', 0, 1, 0),  # ready=1
            ('file2', 'test', 'audio', 'Todo Audio', 'file2.ogg', 0, 0, 0),   # todo (default)
            ('file3', 'test', 'video', 'Trashed Video', 'file3.mp4', 0, 0, 1), # trashed=1
            ('file4', 'test', 'audio', 'Another Ready', 'file4.ogg', 120, 1, 0),  # ready with duration
        ]
        conn.executemany('''
            INSERT INTO files (id, project, file_type, title, filename, duration, ready, trashed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', test_data)
        conn.commit()
        conn.close()
        
        print("Created old schema database:")
        print(f"  Source: {source}")
        print(f"  Records: {len(test_data)}")
        
        # Run migration
        dest = tmpdir / 'new_db.sqlite'
        result = migrate_database(source, dest)
        
        print(f"\nMigration result:")
        print(f"  Copied: {result['copied']}")
        print(f"  Migrated: {result['migrated']}")
        print(f"  Total files: {result['total_files']}")
        print(f"  Tag distribution: {result['tag_distribution']}")
        
        # Verify new schema
        conn = sqlite3.connect(dest)
        conn.row_factory = sqlite3.Row
        
        # Check schema
        cursor = conn.execute("PRAGMA table_info(files)")
        columns = {row['name'] for row in cursor.fetchall()}
        
        assert 'tags' in columns, "New schema missing 'tags' column"
        assert 'ready' not in columns, "Old 'ready' column still exists"
        assert 'trashed' not in columns, "Old 'trashed' column still exists"
        print("\n✓ Schema verified: has 'tags', no 'ready'/'trashed'")
        
        # Check data
        rows = conn.execute("SELECT id, tags, type FROM files ORDER BY id").fetchall()
        
        expected = {
            'file1': ('["ready"]', 'audio'),
            'file2': ('["todo"]', 'audio'),
            'file3': ('["trash"]', 'video'),
            'file4': ('["ready"]', 'audio'),
        }
        
        print("\nVerifying tag mappings:")
        for row in rows:
            id, tags, type_ = row['id'], row['tags'], row['type']
            exp_tags, exp_type = expected[id]
            assert tags == exp_tags, f"{id}: expected {exp_tags}, got {tags}"
            assert type_ == exp_type, f"{id}: expected type {exp_type}, got {type_}"
            print(f"  {id}: {tags} (type: {type_}) ✓")
        
        # Check duration preserved
        dur = conn.execute("SELECT duration FROM files WHERE id='file4'").fetchone()['duration']
        assert dur == 120, f"Duration not preserved: expected 120, got {dur}"
        print(f"\n✓ Duration preserved: file4 has {dur}s")
        
        # Check old table doesn't exist
        try:
            conn.execute("SELECT COUNT(*) FROM files_old")
            assert False, "files_old table should not exist"
        except sqlite3.OperationalError:
            print("✓ Old table properly dropped")
        
        conn.close()
        
        # Verify source is untouched
        conn = sqlite3.connect(source)
        cursor = conn.execute("PRAGMA table_info(files)")
        columns = {row[1] for row in cursor.fetchall()}
        assert 'ready' in columns, "Source database was modified!"
        conn.close()
        print("✓ Source database untouched")
        
        print("\n" + "="*50)
        print("All migration tests passed!")
        print("="*50)
        return 0


if __name__ == '__main__':
    try:
        sys.exit(test_migration())
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
