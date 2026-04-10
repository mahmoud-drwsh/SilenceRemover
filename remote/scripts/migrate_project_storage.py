#!/usr/bin/env python3
"""
Migrate files from flat storage to project-prefixed structure.

Converts:
  storage/audio/file.ogg    → storage/audio/ihya/file.ogg
  storage/video/file.mp4    → storage/video/ihya/file.mp4

Usage:
  cd /var/lib/media-manager
  python3 scripts/migrate_project_storage.py

Safety:
  - Dry-run mode by default (shows what would be moved)
  - Use --execute to perform actual migration
  - Creates backup of database before migration
"""

import os
import sys
import json
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime

# Config
DATA_DIR = Path(os.environ.get('DATA_DIR', '/var/lib/media-manager'))
STORAGE_DIR = DATA_DIR / 'storage'
DB_PATH = DATA_DIR / 'database.db'


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_extension(mime_type: str) -> str:
    """Get file extension for MIME type."""
    mime_to_ext = {
        'audio/mpeg': '.mp3',
        'audio/mp3': '.mp3',
        'audio/mp4': '.m4a',
        'audio/wav': '.wav',
        'audio/x-wav': '.wav',
        'audio/ogg': '.ogg',
        'audio/flac': '.flac',
        'audio/x-flac': '.flac',
        'audio/aac': '.aac',
        'audio/x-m4a': '.m4a',
        'video/mp4': '.mp4',
        'video/x-m4v': '.m4v',
        'video/webm': '.webm',
        'video/ogg': '.ogv',
        'video/quicktime': '.mov',
        'video/x-msvideo': '.avi',
        'video/x-matroska': '.mkv',
    }
    return mime_to_ext.get(mime_type, '.bin')


def dry_run_migrate():
    """Show what would be migrated without moving files."""
    conn = get_db()
    rows = conn.execute(
        'SELECT id, project, type, mime_type FROM files ORDER BY project, type'
    ).fetchall()
    conn.close()

    print("=" * 70)
    print("DRY RUN - No files will be moved")
    print("=" * 70)
    print()

    total = len(rows)
    by_project = {}

    for row in rows:
        ext = get_extension(row['mime_type'])
        old_path = STORAGE_DIR / row['type'] / f"{row['id']}{ext}"
        new_path = STORAGE_DIR / row['type'] / row['project'] / f"{row['id']}{ext}"

        exists = old_path.exists()
        already_migrated = new_path.exists()

        project = row['project']
        if project not in by_project:
            by_project[project] = {'total': 0, 'exists': 0, 'migrated': 0, 'missing': 0}

        by_project[project]['total'] += 1
        if already_migrated:
            by_project[project]['migrated'] += 1
        elif exists:
            by_project[project]['exists'] += 1
        else:
            by_project[project]['missing'] += 1

        status = "✓ already migrated" if already_migrated else ("✓ found" if exists else "✗ NOT FOUND")
        print(f"[{row['project']}] {row['type']:6} {row['id'][:30]:30} {status}")

    print()
    print("=" * 70)
    print("SUMMARY BY PROJECT")
    print("=" * 70)
    for project, stats in sorted(by_project.items()):
        print(f"\n{project}:")
        print(f"  Total files:     {stats['total']}")
        print(f"  Ready to migrate:  {stats['exists']}")
        print(f"  Already migrated:  {stats['migrated']}")
        print(f"  Missing source:    {stats['missing']}")

    print()
    print("=" * 70)
    print(f"Total files in database: {total}")
    print("Run with --execute to perform actual migration")
    print("=" * 70)

    return total > 0


def execute_migrate():
    """Perform actual migration."""
    # Backup database
    backup_path = DATA_DIR / f"database.db.backup.{datetime.now():%Y%m%d_%H%M%S}"
    shutil.copy(DB_PATH, backup_path)
    print(f"Database backed up to: {backup_path}")

    conn = get_db()
    rows = conn.execute(
        'SELECT id, project, type, mime_type FROM files ORDER BY project, type'
    ).fetchall()

    migrated = 0
    skipped = 0
    errors = 0

    print()
    print("Migrating files...")
    print("-" * 70)

    for row in rows:
        ext = get_extension(row['mime_type'])
        old_path = STORAGE_DIR / row['type'] / f"{row['id']}{ext}"
        new_dir = STORAGE_DIR / row['type'] / row['project']
        new_path = new_dir / f"{row['id']}{ext}"

        if new_path.exists():
            print(f"SKIP (already migrated): {row['project']}/{row['type']}/{row['id']}{ext}")
            skipped += 1
            continue

        if not old_path.exists():
            print(f"ERROR (source not found): {old_path}")
            errors += 1
            continue

        # Create directory if needed
        new_dir.mkdir(parents=True, exist_ok=True)

        # Move file
        try:
            shutil.move(str(old_path), str(new_path))
            print(f"MOVED: {old_path} → {new_path}")
            migrated += 1
        except Exception as e:
            print(f"ERROR moving {old_path}: {e}")
            errors += 1

    conn.close()

    print("-" * 70)
    print(f"Migration complete:")
    print(f"  Migrated: {migrated}")
    print(f"  Skipped (already done): {skipped}")
    print(f"  Errors: {errors}")
    print()
    print("Next steps:")
    print("  1. Deploy updated app.py with dual-path support")
    print("  2. Test file streaming from new locations")
    print("  3. Remove old empty directories after verification")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--execute':
        print("EXECUTING MIGRATION")
        print("=" * 70)
        execute_migrate()
    else:
        dry_run_migrate()
        print()
        print("This was a dry run. To execute migration, run:")
        print(f"  python3 {sys.argv[0]} --execute")
