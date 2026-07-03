# Jobs Search-Experience Report

## Scope completed

Implemented all jobs-side tasks from the search-experience briefs in the worktree only:

- blocked queue routes now get a short `next_scrape_at_utc` backoff without being marked as successfully scraped
- blocked queue runs emit `blocked_route`, `blocked_airline`, and `blocked_backoff_min`
- queue-mode `scrape_run` metrics now include `queue_selected_routes`, `queue_left_due_estimate`, and `queue_fill_ratio`
- queue jobs carry the originating due-count so per-shard pressure metrics can be computed correctly
- queue ordering coverage was locked in with tests for never-scraped priority, demand-vs-equal-overdue priority, and extreme-overdue starvation protection

## Files changed

- `browser_scrape_common.py`
- `pipeline/queue_manager.py`
- `pp_db/queries.py`
- `pp_db/queries_routes.py`
- `tests/test_browser_scrape_budget.py`
- `tests/test_browser_scrape_common.py`
- `tests/test_queue_manager.py`
- `tests/test_scoring.py`

## TDD evidence

### Red

Command:

```bash
pytest tests/test_browser_scrape_budget.py tests/test_scoring.py -q
```

Result:

- failed as expected in `test_run_scrape_queue_mode_blocked_route_sets_backoff_and_metric_fields`
- failure showed blocked queue runs were not calling the queue backoff hook:
  - `assert [] == [('SEA', 'JFK', 'jetblue', 90)]`

### Green

Command:

```bash
pytest tests/test_browser_scrape_budget.py tests/test_scoring.py -q
```

Result:

- `26 passed in 0.18s`

### Focused follow-up

Command:

```bash
pytest tests/test_browser_scrape_common.py tests/test_queue_manager.py tests/test_browser_scrape_budget.py tests/test_scoring.py -q
```

Result:

- `26 passed, 2 skipped in 0.18s`
- the two skips are the existing DB-backed queue integration modules when `DATABASE_URL` is unset in this shell

## Full verification

### Lint

Command:

```bash
ruff check .
```

Result:

- `All checks passed!`

### Full test suite

Command:

```bash
pytest tests/ -q
```

Result:

- `235 passed, 8 skipped in 0.81s`

## Notes

- Preserved the invariant that blocked routes are not marked as successfully scraped: `last_scraped_at_utc` remains untouched on the blocked path.
- Used the existing `SCRAPER_BLOCK_COOLDOWN_MIN` setting for the default blocked-route backoff.
- Queue-pressure metrics are computed best-effort and fall back to `None` rather than failing the scrape run.
