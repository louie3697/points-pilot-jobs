## What I implemented

- Added a failing schedule test for Alaska that locks the workflow to four daily slots at `17 1,7,13,19 * * *` and verifies the hours stay outside the 08-11 UTC browser block.
- Added a failing schedule test for Delta that locks the workflow to three daily slots at `0 2 * * *`, `0 8 * * *`, and `0 20 * * *`.
- Updated `.github/workflows/alaska-scrape.yml` to add the 07:17 UTC run and keep the 5-shard matrix unchanged.
- Updated `.github/workflows/delta-browser-scrape.yml` to add the 02:00 UTC run, update the header comment to reflect 3 scheduled slots, and keep the 7-shard matrix unchanged.
- Updated `README.md` so the job table and concurrency note match the new schedules and overlap estimate.

## What I tested and exact results

- `pytest tests/test_alaska_scrape.py tests/test_delta_browser_scrape.py -q`
  - First run: failed as expected on the two new schedule tests.
  - After the workflow edits: `13 passed in 0.07s`
- `ruff check .`
  - Result: `All checks passed!`
- `pytest tests/ -q`
  - Result: `233 passed, 8 skipped in 0.98s`

Pytest prints a startup warning about missing `blake2b` / `blake2s` support in this Python build, but the test runs complete successfully.

## TDD Evidence

### RED

Command:

```bash
pytest tests/test_alaska_scrape.py tests/test_delta_browser_scrape.py -q
```

Observed failures:

```text
FAILED tests/test_alaska_scrape.py::test_alaska_workflow_runs_four_times_daily_with_safe_spacing
E       AssertionError: assert ['17 1,13,19 * * *'] == ['17 1,7,13,19 * * *']

FAILED tests/test_delta_browser_scrape.py::test_delta_workflow_runs_three_times_daily_with_safe_spacing
E       AssertionError: assert ['0 8 * * *', '0 20 * * *'] == ['0 2 * * *', '0 8 * * *', '0 20 * * *']
```

### GREEN

Command:

```bash
pytest tests/test_alaska_scrape.py tests/test_delta_browser_scrape.py -q
```

Observed result after implementation:

```text
13 passed in 0.07s
```

## Files changed

- `.github/workflows/alaska-scrape.yml`
- `.github/workflows/delta-browser-scrape.yml`
- `tests/test_alaska_scrape.py`
- `tests/test_delta_browser_scrape.py`
- `README.md`

## Self-review findings

- The change is schedule-only. Shard counts, scraper code, and env wiring are unchanged.
- The new README concurrency note now reflects the updated cadence and a peak overlap of roughly 17 jobs, still below the 20-job ceiling.
- The workflow comments still explain why the new slots exist and keep the intent close to the cron entries.

## Issues/concerns

- None beyond the existing Python startup warning about missing `blake2` support in this environment.
