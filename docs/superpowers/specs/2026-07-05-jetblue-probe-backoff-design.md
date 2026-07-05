# JetBlue Probe Backoff Design

## Context

JetBlue is already in one-shard daily probe mode after repeated GitHub Actions HTTP 406 blocks.
The current scheduled workflow still probes one queued route across a 90-day scrape horizon, which
expands to roughly two dozen travel dates. Because the shared `HttpScraper` raises
`ScraperBlockedError` only after 4 consecutive 403/406 responses, a fully blocked JetBlue endpoint
can still turn the tiny route probe into a run-level `blocked=True` abort.

## Goal

Reduce the scheduled JetBlue probe enough that it does not hammer the endpoint into the scraper's
blocked circuit breaker while preserving a low-noise daily health signal and manual dispatch path.

## Considered Approaches

1. Keep daily schedule and lower `JETBLUE_SCRAPE_DAYS` from `90` to `1`.
   This sends one queued route for one travel date, so a 406 remains visible in logs/metrics without
   reaching the 4-response circuit breaker threshold. This is the recommended option.
2. Remove the scheduled cron and leave JetBlue manual-only.
   This minimizes traffic most aggressively, but removes the daily signal that tells us when JetBlue
   starts clearing again.
3. Keep the 90-day horizon but run weekly.
   This lowers total weekly volume, but each run can still produce consecutive 406s and mark itself
   blocked, so it does not address the immediate "not getting blocked" goal as directly.

## Design

The scheduled workflow stays at one shard, one queued route, once per day at `20:37 UTC`.
`JETBLUE_SCRAPE_DAYS` becomes `"1"` for scheduled runs, making the run plan one route by one travel
date. No Python scraper logic changes are needed because the existing `dense_sparse_dates()` helper
already returns one date when `max_day=1`.

The workflow comments, unit tests, and README schedule/capacity notes must all describe the probe
mode accurately. The tests should guard the daily cron, one-shard matrix, one-route cap, and one-day
horizon so a future density bump is intentional.

## Validation

Run the focused JetBlue workflow tests first, then the repo's normal pytest and lint checks.
After merge to `origin/main`, dispatch the `jetblue-scrape.yml` workflow and verify the run is green.
Inspect the run log for `1 due routes × 1 dates`; if JetBlue still returns 406, verify it does not
abort as `blocked=True`.
