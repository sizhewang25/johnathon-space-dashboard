# GCAT Space Dashboard

SQLite database built from [Jonathan McDowell's General Catalog of Artificial Space Objects (GCAT)](https://planet4589.org/space/gcat/).

## Setup

```bash
# Ingest TSV data into SQLite
python3 ingest.py

# Query interactively
python3 query.py

# Query via command line
python3 query.py "SELECT COUNT(*) FROM active"
```

## Tables

| Table | Description |
|-------|-------------|
| launchlog | Launch event log |
| active | Currently active satellites |
| satcat | Full satellite catalog |
| currentcat | Current catalog of objects in orbit |
| geotab | Geostationary satellites |
| psatcat | Payload satellite catalog |
| ftocat | Failed-to-orbit catalog |
| deepcat | Deep space objects catalog |

## Example Queries

```sql
-- Count active Starlink satellites
SELECT COUNT(*) FROM active WHERE Name LIKE '%Starlink%';

-- Top 5 satellite owners by count
SELECT Owner, COUNT(*) as cnt FROM active GROUP BY Owner ORDER BY cnt DESC LIMIT 5;

-- Total tracked objects in orbit
SELECT COUNT(*) FROM currentcat;

-- Launches per year
SELECT substr(LaunchDate, 1, 4) as year, COUNT(*) FROM launchlog GROUP BY year ORDER BY year DESC LIMIT 10;
```

## Data Source

TSV files from `../johnathon-space-archives/data/`. No external Python dependencies — uses only stdlib (`sqlite3`).
