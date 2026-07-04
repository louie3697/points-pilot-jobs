# Scraper Observability Flush Design

## Goal

Make browser/httpx scraper completion metrics reliable before hard process exits, so coverage and block dashboards do not miss the exact runs we need for tuning.

## Context

During live validation of the July 4 Delta capacity bump, GitHub logs showed seven successful Delta shards, but Better Stack only received the unblocked shard's `scrape_run` metric. The hard-exit entrypoint comment says to flush briefly before `os._exit(0)`, but the Delta entrypoint sleeps and exits without calling `pipeline.obs.flush()`. Other scraper entrypoints have the same hard-exit shape.

## Approach

Add one shared helper in `pipeline.obs`:

```python
def flush_then_hard_exit(code: int = 0, *, delay_s: float = 0.0) -> None:
    ...
```

The helper optionally sleeps, calls `flush()`, then calls `os._exit(code)`. Existing nodriver scrapers keep the 3-second delay. Alaska and JetBlue, which hard-exit without nodriver sleep today, call the helper without a delay.

## Scope

- Update `cash_browser_scrape.py`, `delta_browser_scrape.py`, `etihad_browser_scrape.py`, `southwest_browser_scrape.py`, `turkish_browser_scrape.py`, `alaska_scrape.py`, and `jetblue_scrape.py`.
- Do not change scrape behavior, queue behavior, budgets, route selection, or heartbeat semantics.
- Add tests that prove helper ordering and guard all scraper hard-exit entrypoints against direct `os._exit(0)`.

## Validation

- Run the jobs test suite and `ruff check .`.
- Merge to `origin/main`.
- Trigger at least one affected GitHub Actions scraper and confirm the run is green.
- Query Better Stack metrics for fresh `scrape_run` rows with `routes_zero`, `blocked`, and queue fields present.
