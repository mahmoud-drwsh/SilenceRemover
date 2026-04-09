#!/usr/bin/env python3
"""
Standalone migration script for Media Manager database.

Migrates from old Flask schema (with ready/trashed columns) to new FastAPI schema (with JSON tags).

Usage:
    sudo python3 migrate_db.py /var/lib/mp3-manager/db.sqlite /var/lib/media-manager/database.db

This will:
1. Copy the source database to the destination
2. Migrate the schema (ready/trashed → tags)
3. Leave the source untouched
"""

import sqlite3
import sys
import shutil
from pathlib import Path


def migrate_database(source_path: Path, dest_path: Path) -> dict:
    """Migrate database from old schema to new tag-based schema.
    
    Args:
        source_path: Path to old Flask database
        dest_path: Path where new database should be created
        
    Returns:
        Migration statistics dict
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Source database not found: {source_path}")
    
    # Ensure destination directory exists
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Copy source to destination (we'll migrate the copy)
    print(f"Copying database...")
    print(f"  Source: {source_path}")
    print(f"  Destination: {dest_path}")
    shutil.copy2(source_path, dest_path)
    
    # Connect and check schema
    conn = sqlite3.connect(dest_path)
    conn.row_factory = sqlite3.Row
    
    # Check if migration is needed
    cursor = conn.execute("PRAGMA table_info(files)")
    columns = {row[1]: row for row in cursor.fetchall()}
    
    if 'ready' not in columns and 'trashed' not in columns:
        print("✓ Database already has new schema (no ready/trashed columns)")
        conn.close()
        return {"copied": True, "migrated": False, "reason": "Already new schema"}
    
    print("\nMigrating schema...")
    print("  Old columns: ready, trashed")
    print("  New column: tags (JSON)")
    
    # Rename old table
    conn.execute('ALTER TABLE files RENAME TO files_old')
    
    # Create new schema
    conn.executescript('''
        CREATE TABLE files (
            id TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'audio',
            title TEXT,
            tags TEXT NOT NULL DEFAULT '[]',
            duration INTEGER DEFAULT 0,
            file_size INTEGER DEFAULT 0,
            mime_type TEXT DEFAULT 'audio/mpeg',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_project ON files(project);
        CREATE INDEX idx_type ON files(type);
    ''')
    
    # Get count before migration
    count = conn.execute("SELECT COUNT(*) FROM files_old").fetchone()[0]
    print(f"\nMigrating {count} records...")
    
    # Check if old schema has file_type or we need to infer from filename
    cursor = conn.execute("PRAGMA table_info(files_old)")
    old_columns = {row[1] for row in cursor.fetchall()}
    has_file_type = 'file_type' in old_columns
    
    # Note: Force using filename-based inference since old mp3-manager schema uses filename
    has_file_type = False
    
    # Migrate data with tag mapping
    if has_file_type:
        # Old schema has file_type column
        cursor = conn.execute('''
            INSERT INTO files (id, project, type, title, tags, duration, file_size, mime_type, created_at)
            SELECT
                id,
                project,
                CASE 
                    WHEN file_type = 'video' THEN 'video' 
                    ELSE 'audio' 
                END as type,
                title,
                CASE
                    WHEN trashed = 1 THEN '["trash"]'
                    WHEN ready = 1 THEN '["ready"]'
                    ELSE '["todo"]'
                END as tags,
                duration,
                0 as file_size,
                CASE 
                    WHEN file_type = 'video' THEN 'video/mp4' 
                    ELSE 'audio/mpeg' 
                END as mime_type,
                CURRENT_TIMESTAMP as created_at
            FROM files_old
        ''')
    else:
        # Infer type from filename extension
        cursor = conn.execute('''
            INSERT INTO files (id, project, type, title, tags, duration, file_size, mime_type, created_at)
            SELECT
                id,
                project,
                CASE 
                    WHEN LOWER(filename) LIKE '%.mp4' OR LOWER(filename) LIKE '%.mov' 
                         OR LOWER(filename) LIKE '%.avi' OR LOWER(filename) LIKE '%.mkv'
                         OR LOWER(filename) LIKE '%.webm' THEN 'video' 
                    ELSE 'audio' 
                END as type,
                title,
                CASE
                    WHEN trashed = 1 THEN '["trash"]'
                    WHEN ready = 1 THEN '["ready"]'
                    ELSE '["todo"]'
                END as tags,
                duration,
                0 as file_size,
                CASE 
                    WHEN LOWER(filename) LIKE '%.mp4' OR LOWER(filename) LIKE '%.mov' 
                         OR LOWER(filename) LIKE '%.avi' OR LOWER(filename) LIKE '%.mkv'
                         OR LOWER(filename) LIKE '%.webm' THEN 'video/mp4' 
                    ELSE 'audio/mpeg' 
                END as mime_type,
                CURRENT_TIMESTAMP as created_at
            FROM files_old
        ''')
    
    # Get tag distribution
    tag_stats = conn.execute('''
        SELECT 
            CASE 
                WHEN tags = '["trash"]' THEN 'trash'
                WHEN tags = '["ready"]' THEN 'ready'
                WHEN tags = '["todo"]' THEN 'todo'
                ELSE 'other'
            END as tag_type,
            COUNT(*) as count
        FROM files
        GROUP BY tag_type
    ''').fetchall()
    
    # Drop old table
    conn.execute('DROP TABLE files_old')
    conn.commit()
    conn.close()
    
    print("\n✓ Migration complete!")
    print(f"\nTag distribution:")
    for row in tag_stats:
        print(f"  {row['tag_type']}: {row['count']} files")
    
    return {
        "copied": True,
        "migrated": True,
        "total_files": count,
        "tag_distribution": {row['tag_type']: row['count'] for row in tag_stats}
    }


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        print(f"\nUsage: python3 {sys.argv[0]} <source_db> <dest_db>")
        print(f"\nExample:")
        print(f"  sudo python3 {sys.argv[0]} /var/lib/mp3-manager/db.sqlite /var/lib/media-manager/database.db")
        sys.exit(1)
    
    source = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    
    if not source.exists():
        print(f"✗ Error: Source database not found: {source}")
        sys.exit(1)
    
    if dest.exists():
        print(f"⚠ Warning: Destination already exists: {dest}")
        response = input("Overwrite? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted.")
            sys.exit(0)
        # Backup existing
        backup = dest.with_suffix('.db.backup')
        shutil.copy2(dest, backup)
        print(f"  Backed up to: {backup}")
    
    try:
        result = migrate_database(source, dest)
        print(f"\n{'='*50}")
        print("Migration successful!")
        print(f"{'='*50}")
        if result.get('migrated'):
            print(f"\nNext steps:")
            print(f"  1. Update service to use new path: {dest}")
            print(f"  2. Restart service: sudo systemctl restart media-manager")
            print(f"  3. Verify: curl http://localhost:8080/<token>/ihya/api/files")
        else:
            print(f"\nDatabase copied but no migration needed.")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
