# GCAT Space Dashboard

Append-only SQLite database tracking daily changes to [Jonathan McDowell's General Catalog of Artificial Space Objects (GCAT)](https://planet4589.org/space/gcat/). Each row is content-hashed; only changed or new records are appended. Full historical state is queryable at any point in time.

## Architecture

```
planet4589.org (source, updated ~weekly)
       │
       ▼
johnathon-space-archives/       ← GitHub Actions daily fetch
  data/*.tsv                       commits if changed
       │
       ▼
johnathon-space-dashboard/      ← ingest.py (hash-dedup append)
  gcat.db (SQLite)                 preserves full history
       │
       ▼
  query.py                      ← SQL queries against any point in time
```

## How It Works: Append-Only Hash Dedup

Every row from the source TSVs is hashed (SHA-256 of all original fields). On each ingest:

1. **New key** → INSERT with today's `_snapshot_date`
2. **Same hash** → SKIP (no change)
3. **Different hash** → INSERT new version with today's `_snapshot_date`
4. **Key gone from source** → mark existing row with `_removed_date = today`

Three metadata columns are added to every table:

| Column | Description |
|--------|-------------|
| `_row_hash` | SHA-256 of all original fields |
| `_snapshot_date` | ISO date when this version was ingested |
| `_removed_date` | ISO date when row disappeared from source (empty string `''` if still present) |

## Tables

| Table | Primary Key | Description |
|-------|-------------|-------------|
| `launchlog` | `Launch_Tag` + `Piece` | Launch event log |
| `active` | `JCAT` | Currently active satellites |
| `satcat` | `JCAT` | Full satellite catalog |
| `currentcat` | `JCAT` | Objects currently in orbit |
| `geotab` | `JCAT` | Geostationary satellites |
| `psatcat` | `JCAT` | Payload satellite catalog |
| `ftocat` | `JCAT` | Failed-to-orbit catalog |
| `deepcat` | `JCAT` | Deep space objects |

Each table has a corresponding `_latest` view (e.g., `active_latest`) showing only the most recent version of each record, including removed ones.

## Quick Start

```bash
# Pull latest archive data and ingest
./sync.sh

# Query interactively
python3 query.py

# Query via command line
python3 query.py "SELECT COUNT(*) FROM active_latest"

# List tables
python3 query.py --tables
```

## Example Queries

### 1. Latest State

Get the current snapshot of all active satellites:

```sql
SELECT * FROM active_latest;
```

### 2. Point-in-Time Query

See what the catalog looked like on a specific date:

```sql
SELECT a.*
FROM active a
JOIN (
    SELECT JCAT, MAX(_snapshot_date) AS max_sd
    FROM active
    WHERE _snapshot_date <= '2026-01-15'
    GROUP BY JCAT
) latest ON a.JCAT = latest.JCAT AND a._snapshot_date = latest.max_sd
WHERE a._removed_date = '' OR a._removed_date > '2026-01-15';
```

### 3. Daily Changes

Records ingested (new or updated) on a specific date:

```sql
SELECT * FROM active WHERE _snapshot_date = '2026-03-19';
```

### 4. New Records on a Day

Objects that appeared for the first time on a given date:

```sql
SELECT * FROM active
WHERE _snapshot_date = '2026-03-19'
  AND JCAT NOT IN (
    SELECT JCAT FROM active WHERE _snapshot_date < '2026-03-19'
  );
```

### 5. Removed on a Day

Objects that disappeared from the source on a given date:

```sql
SELECT * FROM active WHERE _removed_date = '2026-03-19';
```

### 6. History of One Object

Track all versions of a specific object over time:

```sql
SELECT * FROM active WHERE JCAT = 'S44235' ORDER BY _snapshot_date;
```

### 7. Growth Over Time

Count distinct objects by snapshot date:

```sql
SELECT _snapshot_date, COUNT(DISTINCT JCAT) AS total_objects
FROM active
GROUP BY _snapshot_date
ORDER BY _snapshot_date;
```

## Data Source

TSV files from `../johnathon-space-archives/data/`. No external Python dependencies — uses only stdlib (`sqlite3`, `hashlib`).

## License

Data © Jonathan McDowell. This tooling is for personal/research use.
