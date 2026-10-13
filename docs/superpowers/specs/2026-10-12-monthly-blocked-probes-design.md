# Monthly blocked-carrier probes

Reduce wasted scheduled work while Delta, JetBlue, and Turkish reject the runner's requests. Delta and JetBlue currently run weekly; Turkish runs daily. All three will run once per month, on day 1, preserving their existing UTC time slots.

| Workflow | New cron |
| --- | --- |
| delta-browser-scrape.yml | `0 8 1 * *` |
| turkish-browser-scrape.yml | `0 10 1 * *` |
| jetblue-scrape.yml | `37 20 1 * *` |

Preserve manual dispatch, its inputs, concurrency settings, permissions, container references, one-shard/one-route/one-date limits, and all other workflows. Update matching schedule tests and README/comments. No new runtime code, dependencies, or tests are required.

Success means existing schedule assertions pass with monthly values, the repo's tests and lint pass, and the reviewed change is merged onto the remote default branch. GitHub uses schedules from the default branch. Do not trigger known-blocked scrapes merely to verify a cron edit; validate the deployed workflow files and active state instead.

The tradeoff is up to one month before automatic detection of provider recovery; manual dispatch remains available. Better Stack heartbeat expectations may still reflect the old cadence; its connection currently returns 401, so adjusting that external monitoring configuration is unavailable in this task.
