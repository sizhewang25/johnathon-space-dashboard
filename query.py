#!/usr/bin/env python3
"""Query the GCAT SQLite database interactively or via command line."""

import sqlite3
import sys
import os

DB_PATH = os.path.join(os.path.dirname(__file__) or '.', 'gcat.db')


def run_query(conn, sql):
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall()
    if not cols:
        print("(no results)")
        return
    # Calculate column widths
    widths = [len(c) for c in cols]
    for row in rows[:100]:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val) if val else ''))
    # Print
    header = ' | '.join(c.ljust(widths[i]) for i, c in enumerate(cols))
    print(header)
    print('-+-'.join('-' * w for w in widths))
    for row in rows:
        print(' | '.join(str(v if v is not None else '').ljust(widths[i]) for i, v in enumerate(row)))
    print(f"\n({len(rows)} rows)")


def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}\nRun ingest.py first.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)

    if len(sys.argv) > 1:
        run_query(conn, ' '.join(sys.argv[1:]))
    else:
        print("GCAT Query Console (type .tables, .quit, or SQL)")
        while True:
            try:
                sql = input("\nsql> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not sql:
                continue
            if sql == '.quit':
                break
            if sql == '.tables':
                run_query(conn, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                continue
            try:
                run_query(conn, sql)
            except Exception as e:
                print(f"Error: {e}")

    conn.close()


if __name__ == '__main__':
    main()
