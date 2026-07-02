# Award Run Slot Bump Design

## Goal

Reduce remaining due-route pressure by adding one more scheduled daily run slot to the award scrapers that still have meaningful backlog after the shard bump.

## Context

The prior shard bump landed successfully and live validation showed clean provider/runtime health:

- Alaska: 5 shards, 52,387 records, 49 routes, 0 errors, not blocked.
- Delta: 7 shards, 56,553 records, 39 routes, 0 errors, not blocked.
- JetBlue: 5 shards, 20,048 records, 31 routes, 0 errors, not blocked.

The database check after those runs showed the extra shard helped but did not fully clear the Alaska and Delta queues:

- Alaska due-now: `138 -> 89`.
- Delta due-now: `120 -> 87`.
- JetBlue due-now: `44 -> 12`.

Alaska and Delta still hit the per-run time budget before draining all due routes. JetBlue is much closer to drained, so this change leaves JetBlue unchanged.

## Decision

Add one scheduled daily run slot for Alaska and Delta only:

- Alaska: `17 1,13,19 * * *` -> `17 1,7,13,19 * * *`.
- Delta: add a new `0 2 * * *` slot while keeping `0 8 * * *` and `0 20 * * *`.
- JetBlue remains `37 2,14,20 * * *`.

Do not change shard counts, route inventory, scrape horizon, time budgets, entrypoint code, or queue logic in this change.

## Rationale

Alaska at `07:17` creates an even 6-hour cadence (`01:17/07:17/13:17/19:17`) while still staying clear of the `08-11 UTC` browser-heavy award block.

Delta at `02:00` adds a third daily run without stacking on the busy `14:15` cash and `14:37` JetBlue window. The expected overlap remains under the documented 20-job ceiling:

- Alaska `01:17` may briefly overlap Delta `02:00`: `5 + 7 = 12` jobs.
- Delta `02:00` may overlap JetBlue `02:37`: `7 + 5 = 12` jobs.
- In a delayed worst-case, Alaska + Delta + JetBlue could reach `17` jobs, still under 20.

## Files

- `.github/workflows/alaska-scrape.yml`
- `.github/workflows/delta-browser-scrape.yml`
- `tests/test_alaska_scrape.py`
- `tests/test_delta_browser_scrape.py`
- `README.md`

## Testing

Local validation:

```bash
pytest tests/test_alaska_scrape.py tests/test_delta_browser_scrape.py -q
ruff check .
pytest tests/ -q
```

Live validation after merge:

- Dispatch `alaska-scrape.yml` from `main` and confirm 5 shard jobs complete successfully.
- Dispatch `delta-browser-scrape.yml` from `main` and confirm 7 shard jobs complete successfully.
- Query Supabase freshness/due-route counts after the runs complete.
