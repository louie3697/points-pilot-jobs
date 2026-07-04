# Blocked Scraper Backoff Design

## Goal

Reduce JetBlue and Southwest scraper volume while both providers are actively blocking GitHub Actions traffic, without turning off health probes entirely.

## Live Evidence

On July 4, 2026:

- JetBlue `scrape_run` metrics showed 15/15 recent B6 runs blocked, with zero routes scraped and zero records. The latest merged-main validation run blocked all five shards on HTTP 406.
- Southwest's latest scheduled run succeeded at the workflow layer, but all six shards blocked on `southwest (status=403)` after roughly one route per shard.
- Queue pressure remains high: JetBlue has 143 due routes with 100 overdue by 24h; Southwest has 93 due routes with 85 overdue by 24h. Adding more volume would mostly increase blocked requests, not coverage.

## Approach

Put both blocked scrapers into low-rate probe mode:

- JetBlue: one scheduled run per day, one shard, one queued route maximum, keep a 90-day probe horizon.
- Southwest: one scheduled run per day, one shard, one queued route maximum, shorten the scheduled horizon to 30 days to reduce browser/API request volume per probe.

This keeps daily telemetry alive (`blocked`, `blocked_route`, queue pressure, records) while cutting blocked traffic substantially.

## Non-Goals

- Do not remove workflow dispatch; manual on-demand probes should still work.
- Do not delete routes from `pp.routes_queue`.
- Do not change parser logic, block detection, queue scoring, or adaptive cadence.
- Do not expand B6/WN routes while block rates are at 100%.

## Validation

- Tests must assert the new shard counts, schedules, max-leg env overrides, and Southwest 30-day horizon.
- After merge to `main`, trigger JetBlue and Southwest workflows manually and confirm:
  - workflow runs are green,
  - logs show one shard / one selected route,
  - Better Stack receives blocked or productive `scrape_run` metrics with the reduced `queue_selected_routes`.
