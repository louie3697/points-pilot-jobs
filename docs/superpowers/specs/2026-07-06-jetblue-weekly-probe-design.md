# JetBlue Weekly Probe Backoff Design

## Context

The previous JetBlue backoff reduced scheduled GitHub Actions traffic to one route by one travel
date per daily probe. A live run on `2026-07-05T22:25:30Z` still received HTTP 406 from JetBlue,
but no longer tripped the run-level blocked circuit breaker:

- `JETBLUE_SCRAPE_DAYS: 1`
- `Cron queue mode (shard 0/1): 1 due routes × 1 dates`
- one HTTP 406
- `blocked=False` in `29.0s`

That confirms the one-date backoff fixed the run-level blocked abort, but the endpoint is still
rejecting GitHub Actions traffic. A daily 406 is more noise than signal while JetBlue remains fully
blocked.

## Goal

Reduce scheduled JetBlue pressure further while preserving an automatic canary that tells us when
JetBlue starts clearing again.

## Considered Approaches

1. Change the daily one-date canary to a weekly one-date canary.
   This cuts automatic JetBlue traffic by about 86% while keeping a regular unblock signal.
   Recommended.
2. Remove the schedule entirely and leave only `workflow_dispatch`.
   This eliminates scheduled 406s, but makes unblock detection manual and easier to forget.
3. Keep the daily schedule because it no longer marks `blocked=True`.
   This is safe for our runner status, but still sends a known-failing request every day.

## Design

Keep the current low-volume scheduled probe shape:

- `matrix.shard: [0]`
- `JETBLUE_SHARDS: "1"`
- `JETBLUE_MAX_LEGS_PER_SHARD: "1"`
- `JETBLUE_SCRAPE_DAYS: "1"`

Change only the scheduled cadence from daily `37 20 * * *` to weekly Sunday `37 20 * * 0`.
Keep `workflow_dispatch` so we can run a manual canary when testing changes or checking if JetBlue
has unblocked.

Update the JetBlue workflow comments, unit tests, and README operational notes so they consistently
describe a weekly one-route, one-date probe while HTTP 406 remains blocked.

## Validation

Run the focused JetBlue workflow test, the full repo test suite, ruff, and `git diff --check`.
After merge to `origin/main`, verify the workflow YAML on main contains the weekly cron. For the
repo deploy validation, manually dispatch the workflow once and confirm it still runs green with
one route by one date and `blocked=False`; this consumes one intentional canary request.
