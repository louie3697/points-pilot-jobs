# Reduced Recovery Scrapes Design

## Context

The post-purge health check found the database, API, public UI, Alaska scraper, and core scheduled
jobs operational. Three airline recovery paths need correction:

- Turkish still launches three shards over five travel dates each day even though the current
  upstream availability response is unsuccessful and produces no usable payload.
- Delta is already a weekly one-route recovery probe in `origin/main`, but its Better Stack
  heartbeat still expects a daily check and therefore reports a false outage.
- JetBlue is already a weekly one-route, one-date recovery probe while HTTP 406 persists; its
  eight-day heartbeat window is consistent with that cadence.
- A legacy generic scraper heartbeat has not represented an active service since June and should
  no longer contribute a false outage.

The healthy Alaska, cash, Southwest, Etihad, transfer, API, and UI paths are outside this change.

## Goal

Reduce known-failing scheduled traffic while preserving automatic recovery detection, and make
heartbeat state reflect the schedules that actually run.

## Considered Approaches

1. Disable Turkish, Delta, and JetBlue schedules entirely. This minimizes traffic but removes the
   automatic signal that an upstream has recovered.
2. Keep every current schedule and only silence heartbeat alerts. This hides noise but continues
   wasteful Turkish traffic and makes operational status less truthful.
3. Keep one bounded recovery canary per affected airline and align monitoring to the real cadence.
   This preserves recovery detection at minimal cost and is the selected approach.

## Design

### Turkish workflow

Keep the daily 10:00 UTC schedule and manual route dispatch. Change scheduled/default execution
from three shards over five travel dates to exactly:

- matrix `shard: [0]`
- `TURKISH_SHARDS: "1"`
- `TURKISH_MAX_LEGS_PER_SHARD: "1"`
- `TURKISH_SCRAPE_DAYS: "1"`
- unchanged `TURKISH_SHARD_INDEX: ${{ matrix.shard }}`

`config.settings.CRON_MAX_LEGS_PER_SHARD` already reads `TURKISH_MAX_LEGS_PER_SHARD`, so no scraper
runtime change is required. Manual single-route dispatch remains available and uses the supplied
route/dates; when dates are blank it inherits the one-date window.

Update comments and README operational documentation to describe a daily one-route, one-date
recovery canary. Add a workflow contract test that parses the YAML and locks the cron, manual
dispatch, matrix, route cap, date count, shard count, and shard-index mapping together.

### Delta and JetBlue code

Do not change their workflows. Delta is already weekly Sunday at 08:00 UTC with one shard, one
route, and one date. JetBlue is already weekly Sunday at 20:37 UTC with one shard, one route, and
one date. Correct the stale README Delta schedule while documenting the reduced Turkish shape.

### Better Stack operations

After the workflow change reaches `origin/main`:

- change the Delta heartbeat expectation from daily to weekly with enough grace for a delayed
  GitHub Actions run;
- keep Turkish daily and JetBlue weekly;
- pause the obsolete generic scraper heartbeat rather than delete historical monitoring data;
- do not enable or change notification recipients in this task.

These monitoring changes are operational configuration, not repository code.

## Validation

- Use TDD for the Turkish workflow contract test.
- Run the focused Turkish tests, then the full Python 3.11 test suite.
- Run Ruff with the repository exclusions plus local virtual-environment exclusions.
- Parse the workflow YAML and run `git diff --check`.
- Merge the PR to `origin/main` and verify the squash commit is on the remote default branch.
- Manually dispatch the Turkish workflow from `main` with blank route inputs. Confirm the run
  creates one matrix job and its logs show no more than one route by one date. The upstream may
  still return an unsuccessful response; that is an expected red recovery signal, while the
  bounded request shape is the deployment acceptance criterion.
- Re-read the affected Better Stack heartbeats and confirm their resulting cadence/status.
