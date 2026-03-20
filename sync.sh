#!/usr/bin/env bash
# Sync GCAT archive and ingest into SQLite
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ARCHIVE_DIR="$SCRIPT_DIR/../johnathon-space-archives"

echo "==> Pulling latest archive data..."
cd "$ARCHIVE_DIR"
git pull

echo "==> Running ingest..."
cd "$SCRIPT_DIR"
python3 ingest.py

echo "==> Done."
