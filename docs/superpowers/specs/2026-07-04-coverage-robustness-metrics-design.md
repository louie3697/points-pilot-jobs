# Coverage Robustness Metrics Design

## Goal

Use the live admin coverage report plus queue/log metrics from July 4, 2026 to improve scraper density safely, without adding more routes into scrapers that are currently blocked, zero-yielding, or time-budget constrained.

## Inputs

- Admin coverage report snapshot: 967,580 serving award rows, 669 award routes, 6 airlines, 42.1% cash-to-award, 54.8h award freshness, 49.7h cash freshness.
- Baseline progress: +600,984 award rows since 2026-06-25, cash-to-award down from 49.5% to 42.1%.
- Queue scorecard: Alaska is healthy; Delta has no 24h-overdue routes but stops early on its 45-minute runner budget; JetBlue has heavy backlog and latest runs blocked with HTTP 406; Southwest has heavy backlog and latest runs abort after one useful route with HTTP 403; Turkish runs complete but emit zero records; Etihad is healthy.
- Cash scorecard: latest Actions cash runs are healthy and unblocked, but cash freshness lags because the scraper only covers 30 days while award coverage now reaches much deeper.

## Design

1. **Delta capacity uses existing workflow headroom.** Keep the current 3 daily slots and 7 shards, but set `CRON_TIME_BUDGET_S=7200` in the Delta workflow. The workflow timeout is already 150 minutes and recent shards stop after 45 minutes despite no block, so this clears more assigned routes without increasing parallel job pressure.

2. **Cash density grows by horizon, not route limit.** Keep 6 shards and 3 daily cash slots, but raise `CASH_SCRAPE_DAYS` from 30 to 45. Recent shards did not hit `CASH_TOP_ROUTES=800`, so increasing that limit would not help; the active limiter is the days-ahead window.

3. **Award scraper metrics identify zero-yield runs.** Add `routes_zero` to the shared award `scrape_run` metric. A successful zero-record scrape remains a completed scrape and should still be marked adaptively, but the metric must make Turkish-style zero-yield runs visible.

4. **Budget log text distinguishes shard assignment from total backlog.** Keep `due_routes` as the total due backlog for queue pressure, but make stopped-early logs say how many assigned routes were reached and what total due backlog remains. This prevents the Delta log from reading as if a single shard was assigned 71 routes.

## Out Of Scope

- No new route seeds in this pass. Delta, JetBlue, Southwest, and Turkish all need robustness/capacity work before route expansion.
- No JetBlue HTTP 406 parser/transport rewrite in this pass. It should be its own focused repair after this observability/capacity bump lands.
- No Southwest WAF strategy rewrite in this pass.
- No Turkish parser investigation in this pass.

## Validation

- Unit/workflow tests must cover the new `routes_zero` metric, Delta `CRON_TIME_BUDGET_S`, and cash `CASH_SCRAPE_DAYS=45`.
- Run `pytest tests/ -q` and `ruff check .` in the jobs worktree.
- After merge to `main`, trigger `delta-browser-scrape` and `cash-browser-scrape` via `workflow_dispatch`, then confirm the runs are green and their logs show the new capacity settings/metrics path.
