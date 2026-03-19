#!/usr/bin/env python3
"""Ingest GCAT TSV files into a SQLite database."""

import sqlite3
import os
import re

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'johnathon-space-archives', 'data')
DB_PATH = os.path.join(os.path.dirname(__file__) or '.', 'gcat.db')

TABLES = ['launchlog', 'active', 'satcat', 'currentcat', 'geotab', 'psatcat', 'ftocat', 'deepcat']


def clean_col(name):
    """Clean column name for SQL compatibility."""
    name = name.strip().replace(' ', '_').replace('/', '_').replace('-', '_').replace('#', '')
    name = re.sub(r'[^a-zA-Z0-9_]', '', name)
    return name or 'col'


def ingest_tsv(conn, table_name, filepath):
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    # Find header: first line starting with # that has tabs (column header row)
    # The header line starts with #ColName\tCol2\t... 
    # Pure comment lines start with # followed by space/text without tab structure
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('#') and '\t' in stripped:
            header_idx = i
            break
    
    if header_idx is None:
        # Fallback: first non-empty, non-comment line
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                header_idx = i
                break

    if header_idx is None:
        print(f"  {table_name}: no header found, skipping")
        return 0

    header_line = lines[header_idx].rstrip('\n')
    if header_line.startswith('#'):
        header_line = header_line[1:]  # strip leading #
    raw_cols = header_line.split('\t')
    columns = [clean_col(c) for c in raw_cols]
    # Deduplicate
    seen = {}
    for i, c in enumerate(columns):
        if c in seen:
            seen[c] += 1
            columns[i] = f"{c}_{seen[c]}"
        else:
            seen[c] = 0

    conn.execute(f"DROP TABLE IF EXISTS [{table_name}]")
    col_defs = ', '.join(f'[{c}] TEXT' for c in columns)
    conn.execute(f"CREATE TABLE [{table_name}] ({col_defs})")

    placeholders = ', '.join(['?'] * len(columns))
    insert_sql = f"INSERT INTO [{table_name}] VALUES ({placeholders})"

    rows = []
    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        fields = line.rstrip('\n').split('\t')
        # Strip whitespace, pad/truncate to column count
        fields = [f.strip() for f in fields]
        while len(fields) < len(columns):
            fields.append('')
        fields = fields[:len(columns)]
        rows.append(fields)

    conn.executemany(insert_sql, rows)
    conn.commit()
    return len(rows)


def main():
    conn = sqlite3.connect(DB_PATH)
    print(f"Database: {DB_PATH}\n")

    for table in TABLES:
        path = os.path.join(DATA_DIR, f'{table}.tsv')
        if not os.path.exists(path):
            print(f"  {table}: FILE NOT FOUND at {path}")
            continue
        count = ingest_tsv(conn, table, path)
        print(f"  {table}: {count:,} rows")

    conn.close()
    size = os.path.getsize(DB_PATH)
    print(f"\nDatabase size: {size / 1024 / 1024:.1f} MB")


if __name__ == '__main__':
    main()
