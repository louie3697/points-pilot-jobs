# point-pilot-jobs

Scheduled maintenance jobs for point_pilot, run as GitHub Actions cron workflows.
Each job is a self-contained Python script that talks to the shared MotherDuck
database (`md:point_pilot`).

## Jobs

| Script | Workflow | Schedule | What it does |
|---|---|---|---|
| `cleanup_flights.py` | `cleanup-flights.yml` | daily 03:15 UTC | Deletes rows from `flights` whose departure `date` is older than yesterday (UTC). |

### `cleanup_flights.py`

Deletes every flight older than yesterday (UTC) — keeps yesterday plus all future
dates. Cleanup is anchored to the flight `date`, not `expires_at` (which is only a
scrape-freshness TTL), matching the scraper's own `expire_stale_flights()`.

```bash
python cleanup_flights.py            # delete stale rows
python cleanup_flights.py --dry-run  # report how many would be deleted, delete nothing
```

## Setup

1. Install deps: `pip install -r requirements.txt`
2. Export a MotherDuck token (the `duckdb` package picks it up automatically):
   ```bash
   export MOTHERDUCK_TOKEN=...   # https://app.motherduck.com/settings/tokens
   ```

### GitHub Actions

Add the token as a repository secret named **`MOTHERDUCK_TOKEN`**
(Settings → Secrets and variables → Actions). The workflows also expose a manual
**Run workflow** button (`workflow_dispatch`) with a `dry_run` toggle.
