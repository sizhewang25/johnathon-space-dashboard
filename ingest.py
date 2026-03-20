#!/usr/bin/env python3
"""Ingest GCAT TSV files into a SQLite database with hash-dedup schema."""

import sqlite3
import os
import re

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


def main():
    # Remove old DB for clean schema creation
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    
    conn = sqlite3.connect(DB_PATH)
    print(f"Database: {DB_PATH}\n")

    for table in TABLES:
        path = os.path.join(DATA_DIR, f'{table}.tsv')
        if not os.path.exists(path):
            print(f"  {table}: FILE NOT FOUND at {path}")
            continue
        
        columns = parse_tsv_header(path)
        if columns is None:
            print(f"  {table}: no header found, skipping")
            continue
        
        create_table(conn, table, columns)
        print(f"  {table}: created with {len(columns)} columns + 3 metadata cols, keys={TABLE_KEYS[table]}")

    conn.close()
    print("\nSchema creation complete (empty tables).")


if __name__ == '__main__':
    main()
