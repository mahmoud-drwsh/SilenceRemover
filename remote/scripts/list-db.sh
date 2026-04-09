#!/bin/bash
# List all database records
# Usage: ./list-db.sh

cd "$(dirname "$0")/.."

DB_PATH="${DATA_DIR:-./data}/database.db"

if [ ! -f "$DB_PATH" ]; then
    echo "No database found at: $DB_PATH"
    echo "Run the server first to create the database."
    exit 1
fi

echo "Database: $DB_PATH"
echo ""

sqlite3 "$DB_PATH" <<EOF
.headers on
.mode table
SELECT * FROM files ORDER BY project, id;
EOF
