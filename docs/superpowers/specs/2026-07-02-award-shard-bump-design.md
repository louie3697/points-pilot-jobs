# Award Shard Bump Design

## Goal

Reduce queue wait for the Alaska, Delta, and JetBlue award scrapers by adding one parallel GitHub Actions shard to each scheduled run.

## Context

The prior coverage bump expanded international route coverage and completed live validation successfully. The follow-up database check still showed due-route pressure on the three expanded award queues:

- Alaska: 138 routes due now after the bump.
- Delta: 120 routes due now after the bump.
- JetBlue: 44 routes due now after the bump.

The live workflow logs showed each scraper finishing cleanly with zero provider errors and no blocking, but stopping at the per-run wall-clock budget before draining every due route. Adding one shard per scheduled run should increase parallel queue drain without changing route inventory, scrape horizon, or cron cadence.

## Decision

Add one matrix shard to each affected award workflow:

- Alaska: `ALASKA_SHARDS` `4 -> 5`, matrix `[0, 1, 2, 3, 4]`.
- Delta: `DELTA_SHARDS` `6 -> 7`, matrix `[0, 1, 2, 3, 4, 5, 6]`.
- JetBlue: `JETBLUE_SHARDS` `4 -> 5`, matrix `[0, 1, 2, 3, 4]`.

Do not add another cron slot in this change. The workflows already have staggered schedules; this is the smallest throughput bump that directly answers the request for another shard. If due queues remain high after 24-48 hours, the next knob is schedule frequency or per-run time budget.

## Expected Impact

- Alaska and JetBlue gain 25% more parallel route partitions per run.
- Delta gains about 16.7% more parallel route partitions per run.
- Peak Actions concurrency remains within the documented 20-job ceiling. The busiest planned overlap remains cash plus a browser award scraper, now roughly 13 jobs for cash plus Delta.
- Existing sharding logic remains unchanged: each workflow matrix must stay `0..n-1`, and each `<AIRLINE>_SHARDS` env value must equal the matrix length.

## Files

- `.github/workflows/alaska-scrape.yml`
- `.github/workflows/delta-browser-scrape.yml`
- `.github/workflows/jetblue-scrape.yml`
- `tests/test_alaska_scrape.py`
- `tests/test_delta_browser_scrape.py`
- `tests/test_jetblue_scrape.py`
- `README.md`

## Testing

Local validation must run:

```bash
pytest tests/test_alaska_scrape.py tests/test_delta_browser_scrape.py tests/test_jetblue_scrape.py -q
ruff check .
```

Before merge, run the full test suite if targeted validation passes:

```bash
pytest tests/ -q
```

After merge, dispatch the three live workflows and confirm their matrix jobs match the new shard counts and complete successfully:

- `alaska-scrape.yml`: 5 jobs.
- `delta-browser-scrape.yml`: 7 jobs.
- `jetblue-scrape.yml`: 5 jobs.
