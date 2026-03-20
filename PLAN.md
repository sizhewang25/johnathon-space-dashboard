# GCAT Space Dashboard — Architecture Plan

## Overview

Append-only SQLite database tracking daily changes to Jonathan McDowell's GCAT space object catalog. Each row is content-hashed; only changed/new records are appended. Full historical state is queryable at any point in time.

## Data Flow

```
planet4589.org (source, updated ~weekly)
       │
       ▼
jonathon-space-archives/        ← GitHub Actions daily 6 AM EDT
  data/*.tsv                       fetches TSVs, commits if changed
       │
       ▼
jonathon-space-dashboard/       ← ingest.py runs after each pull
  gcat.db (SQLite)                 hash-dedup append, preserves history
       │
       ▼
  query.py                      ← SQL queries against any point in time
```

## Schema Design

### Approach: Append-Only with Row-Level Hash Dedup

Every table keeps its original GCAT columns plus three metadata columns:

| Column | Type | Description |
|--------|------|-------------|
| `_row_hash` | TEXT | SHA-256 of all original fields concatenated |
| `_snapshot_date` | TEXT | ISO date when this version was ingested (e.g. `2026-03-19`) |
| `_removed_date` | TEXT | ISO date when row disappeared from source (NULL if still present) |

### Primary Keys per Table

| Table | Natural Key | Notes |
|-------|-------------|-------|
| `launchlog` | `Launch_Tag` + `Piece` | Composite — one launch can deploy multiple pieces |
| `active` | `JCAT` | Jonathan's catalog ID, unique per object |
| `satcat` | `JCAT` | Same catalog ID system |
| `currentcat` | `JCAT` | Same catalog ID system |
| `geotab` | `JCAT` | Same catalog ID system |
| `psatcat` | `JCAT` | Same catalog ID system |
| `ftocat` | `JCAT` | Same catalog ID system |
| `deepcat` | `JCAT` | Same catalog ID system |

### Indexes

```sql
-- Per table (example for active):
CREATE INDEX idx_active_key ON active (JCAT);
CREATE INDEX idx_active_snapshot ON active (_snapshot_date);
CREATE INDEX idx_active_key_snapshot ON active (JCAT, _snapshot_date DESC);
```

## Ingest Logic (ingest.py)

```
For each table:
  1. Parse TSV → extract rows with all original fields
  2. For each row:
     a. Compute key (JCAT or Launch_Tag+Piece)
     b. Compute SHA-256 hash of all original fields joined by \t
     c. Look up latest row in DB for this key:
        SELECT _row_hash FROM table 
        WHERE key = ? ORDER BY _snapshot_date DESC LIMIT 1
     d. If no existing row → INSERT (new record, first_seen)
     e. If existing hash == new hash → SKIP (no change)
     f. If existing hash != new hash → INSERT new version with today's date
  3. Detect removals:
     a. Get all keys present in DB's latest snapshot but NOT in today's source
     b. UPDATE the latest row for that key: SET _removed_date = today's date
  4. Print summary: new records, updated records, removed records, unchanged
```

### Performance Notes

- Batch all INSERTs in a single transaction
- Use a temp table or in-memory dict for hash lookups (faster than per-row SELECT)
- Full ingest of ~224k rows should complete in < 10 seconds

## Query Patterns

### Latest state (current view)

```sql
-- Latest version of each active satellite (equivalent to raw TSV today)
SELECT a.* FROM active a
INNER JOIN (
  SELECT JCAT, MAX(_snapshot_date) as max_date 
  FROM active 
  WHERE _removed_date IS NULL
  GROUP BY JCAT
) latest ON a.JCAT = latest.JCAT AND a._snapshot_date = latest.max_date;
```

Consider creating a view for convenience:
```sql
CREATE VIEW active_latest AS
SELECT a.* FROM active a
INNER JOIN (
  SELECT JCAT, MAX(_snapshot_date) as max_date 
  FROM active WHERE _removed_date IS NULL GROUP BY JCAT
) l ON a.JCAT = l.JCAT AND a._snapshot_date = l.max_date;
```

### Point-in-time query

```sql
-- State of active satellites as of April 1
SELECT a.* FROM active a
INNER JOIN (
  SELECT JCAT, MAX(_snapshot_date) as max_date 
  FROM active 
  WHERE _snapshot_date <= '2026-04-01' 
    AND (_removed_date IS NULL OR _removed_date > '2026-04-01')
  GROUP BY JCAT
) snap ON a.JCAT = snap.JCAT AND a._snapshot_date = snap.max_date;
```

### What changed on a specific day

```sql
-- All records ingested on March 20 (new + updated)
SELECT * FROM active WHERE _snapshot_date = '2026-03-20';

-- Only new satellites (first appearance)
SELECT * FROM active a
WHERE _snapshot_date = '2026-03-20'
AND NOT EXISTS (
  SELECT 1 FROM active b WHERE b.JCAT = a.JCAT AND b._snapshot_date < '2026-03-20'
);

-- Satellites removed on that day
SELECT * FROM active 
WHERE _removed_date = '2026-03-20';
```

### History of a single object

```sql
-- Full change history of a specific satellite
SELECT * FROM active WHERE JCAT = 'S62492' ORDER BY _snapshot_date;
```

### Growth over time

```sql
-- Active satellite count per snapshot date
SELECT _snapshot_date, COUNT(DISTINCT JCAT) as active_count
FROM active WHERE _removed_date IS NULL
GROUP BY _snapshot_date ORDER BY _snapshot_date;
```

## Automation

### Sync Script (sync.sh)

```bash
#!/bin/bash
# Run after GitHub Actions updates the archive
cd ~/workspace/johnathon-space-archives && git pull
cd ~/workspace/johnathon-space-dashboard && python3 ingest.py
```

### Options for triggering:
1. **Cron job** — run sync.sh daily at 6:30 AM EDT (30 min after archive workflow)
2. **GitHub Actions webhook** — trigger on archive repo push
3. **Manual** — `python3 ingest.py` whenever needed

## File Structure

```
johnathon-space-dashboard/
├── gcat.db              ← SQLite database (gitignored)
├── ingest.py            ← Append-only hash-dedup ingestion
├── query.py             ← Interactive/CLI SQL query tool
├── sync.sh              ← Pull archive + run ingest
├── PLAN.md              ← This file
├── README.md            ← Usage docs
└── .gitignore           ← gcat.db, __pycache__
```

## Storage Estimates

- **Day 1:** ~38 MB (full initial load, same as current)
- **Per day after:** ~0-2 MB (only changed rows appended; source updates ~weekly)
- **Per year:** ~50-100 MB estimate (depends on constellation deployment pace)
- **Threshold:** If DB exceeds 500 MB, consider archiving old snapshots or switching to DuckDB/Parquet

## Future Enhancements (not in scope now)

- [ ] Web dashboard with charts (constellation growth, launch cadence)
- [ ] Discord notifications on significant changes (new constellation detected, mass deorbit event)
- [ ] DuckDB migration if query performance degrades
- [ ] Export snapshots to Parquet for external analysis tools
- [ ] REST API for programmatic queries
