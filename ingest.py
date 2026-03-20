#!/usr/bin/env python3
"""Ingest GCAT TSV files into a SQLite database with hash-dedup schema."""

import sqlite3
import os
import re
import hashlib
from datetime import date

DATA_DIR = os.path.join(os.path.dirname(__file__) or '.', '..', 'johnathon-space-archives', 'data')
DB_PATH = os.path.join(os.path.dirname(__file__) or '.', 'gcat.db')

TABLES = ['launchlog', 'active', 'satcat', 'currentcat', 'geotab', 'psatcat', 'ftocat', 'deepcat']

# Natural key columns per table
TABLE_KEYS = {
    'launchlog': ['Launch_Tag', 'Piece'],
    'active':     ['JCAT'],
    'satcat':     ['JCAT'],
    'currentcat': ['JCAT'],
    'geotab':     ['JCAT'],
    'psatcat':    ['JCAT'],
    'ftocat':     ['JCAT'],
    'deepcat':    ['JCAT'],
}

METADATA_COLS = ['_row_hash', '_snapshot_date', '_removed_date']


def clean_col(name):
    """Clean column name for SQL compatibility."""
    name = name.strip().replace(' ', '_').replace('/', '_').replace('-', '_').replace('#', '')
    name = re.sub(r'[^a-zA-Z0-9_]', '', name)
    return name or 'col'


def parse_tsv_header(filepath):
    """Parse a GCAT TSV file and return (columns, header_line_index).
    
    Header line starts with # and contains tabs.
    Column names are cleaned for SQL compatibility.
    """
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        for i, line in enumerate(f):
            stripped = line.strip()
            if stripped.startswith('#') and '\t' in stripped:
                header_line = stripped[1:]  # strip leading #
                raw_cols = header_line.split('\t')
                columns = [clean_col(c) for c in raw_cols]
                # Deduplicate
                seen = {}
                for j, c in enumerate(columns):
                    if c in seen:
                        seen[c] += 1
                        columns[j] = f"{c}_{seen[c]}"
                    else:
                        seen[c] = 0
                return columns
    return None


def create_table(conn, table_name, columns):
    """Create table with original columns plus metadata columns and indexes."""
    conn.execute(f"DROP TABLE IF EXISTS [{table_name}]")
    
    col_defs = ', '.join(f'[{c}] TEXT' for c in columns)
    meta_defs = ', '.join(f'[{c}] TEXT' for c in METADATA_COLS)
    conn.execute(f"CREATE TABLE [{table_name}] ({col_defs}, {meta_defs})")
    
    # Index on key columns
    key_cols = TABLE_KEYS[table_name]
    key_col_sql = ', '.join(f'[{c}]' for c in key_cols)
    conn.execute(f"CREATE INDEX [idx_{table_name}_key] ON [{table_name}] ({key_col_sql})")
    
    # Index on _snapshot_date
    conn.execute(f"CREATE INDEX [idx_{table_name}_snapshot] ON [{table_name}] ([_snapshot_date])")
    
    # Composite index on key + snapshot_date DESC
    conn.execute(f"CREATE INDEX [idx_{table_name}_key_snapshot] ON [{table_name}] ({key_col_sql}, [_snapshot_date] DESC)")
    
    conn.commit()


def parse_tsv_rows(filepath):
    """Yield data rows (non-comment, non-blank) as lists of fields."""
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            yield stripped.split('\t')


def compute_hash(fields):
    """SHA-256 of all fields joined by tab."""
    return hashlib.sha256('\t'.join(fields).encode('utf-8')).hexdigest()


def load_existing_hashes(conn, table_name, key_cols):
    """Load latest _row_hash per key from DB. Returns dict key_tuple -> hash."""
    key_sql = ', '.join(f'[{c}]' for c in key_cols)
    # Get max snapshot_date per key, then join to get hash
    # For duplicate keys, we want ALL (key, hash) pairs from latest snapshot
    # Use rowid to get the last inserted row per key+snapshot combo
    query = f"""
        SELECT {key_sql}, [_row_hash], rowid
        FROM [{table_name}]
        WHERE [_snapshot_date] = (SELECT MAX([_snapshot_date]) FROM [{table_name}])
        ORDER BY rowid
    """
    result = {}  # key -> list of hashes
    try:
        for row in conn.execute(query):
            key = tuple(row[:len(key_cols)])
            h = row[len(key_cols)]
            result.setdefault(key, []).append(h)
    except sqlite3.OperationalError:
        pass  # table doesn't exist yet
    return result


def table_exists(conn, table_name):
    r = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
    return r[0] > 0


def detect_removals(conn, table_name, key_cols, source_keys, today):
    """Detect keys present in DB but missing from source. Update _removed_date on latest row."""
    key_sql = ', '.join(f'[{c}]' for c in key_cols)
    
    # Get all active keys from DB (latest snapshot, not yet removed)
    # We need the rowid of the latest row per key to update only that one
    query = f"""
        SELECT {key_sql}, MAX(rowid) as latest_rowid
        FROM [{table_name}]
        WHERE [_removed_date] = '' OR [_removed_date] IS NULL
        GROUP BY {key_sql}
    """
    
    rowids_to_update = []
    try:
        for row in conn.execute(query):
            key = tuple(row[:len(key_cols)])
            rowid = row[len(key_cols)]
            if key not in source_keys:
                rowids_to_update.append((today, rowid))
    except sqlite3.OperationalError:
        return 0
    
    if rowids_to_update:
        conn.executemany(
            f"UPDATE [{table_name}] SET [_removed_date] = ? WHERE rowid = ?",
            rowids_to_update
        )
        conn.commit()
    
    return len(rowids_to_update)


def ingest_table(conn, table_name, filepath):
    """Ingest a single TSV file with hash-dedup logic. Returns (new, updated, unchanged)."""
    columns = parse_tsv_header(filepath)
    if columns is None:
        print(f"  {table_name}: no header found, skipping")
        return 0, 0, 0

    key_cols = TABLE_KEYS[table_name]
    key_indices = [columns.index(k) for k in key_cols]
    today = date.today().isoformat()

    # Create table if not exists
    if not table_exists(conn, table_name):
        create_table(conn, table_name, columns)

    # Load existing hashes
    existing = load_existing_hashes(conn, table_name, key_cols)

    # Process rows — track per-key occurrence index for duplicate key support
    new_count = 0
    updated_count = 0
    unchanged_count = 0
    to_insert = []
    key_occurrence = {}  # track which occurrence of each key we're on

    all_cols = columns + METADATA_COLS
    placeholders = ', '.join(['?'] * len(all_cols))
    col_sql = ', '.join(f'[{c}]' for c in all_cols)
    insert_sql = f"INSERT INTO [{table_name}] ({col_sql}) VALUES ({placeholders})"

    for fields in parse_tsv_rows(filepath):
        # Pad or truncate to match column count
        if len(fields) < len(columns):
            fields = fields + [''] * (len(columns) - len(fields))
        elif len(fields) > len(columns):
            fields = fields[:len(columns)]

        row_hash = compute_hash(fields)
        key = tuple(fields[i] for i in key_indices)
        
        # Track occurrence index for duplicate keys
        occ = key_occurrence.get(key, 0)
        key_occurrence[key] = occ + 1
        
        prev_hashes = existing.get(key, [])
        if occ < len(prev_hashes) and prev_hashes[occ] == row_hash:
            unchanged_count += 1
            continue
        
        if occ >= len(prev_hashes):
            new_count += 1
        else:
            updated_count += 1

        to_insert.append(fields + [row_hash, today, ''])

    # Batch insert
    if to_insert:
        conn.executemany(insert_sql, to_insert)
        conn.commit()

    # Removal detection: find keys in DB (latest snapshot, not removed) but missing from source
    removed_count = detect_removals(conn, table_name, key_cols, key_occurrence, today)

    return new_count, updated_count, unchanged_count, removed_count


def main():
    conn = sqlite3.connect(DB_PATH)
    print(f"Database: {DB_PATH}\n")

    for table in TABLES:
        path = os.path.join(DATA_DIR, f'{table}.tsv')
        if not os.path.exists(path):
            print(f"  {table}: FILE NOT FOUND at {path}")
            continue

        new, updated, unchanged, removed = ingest_table(conn, table, path)
        total = new + updated + unchanged
        print(f"  {table}: {total} rows — {new} new, {updated} updated, {unchanged} unchanged, {removed} removed")

    conn.close()
    print("\nIngest complete.")


if __name__ == '__main__':
    main()
