# Award Run Slot Bump Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one more daily scheduled run slot to Alaska and Delta award scrapers to reduce queue wait.

**Architecture:** This is a GitHub Actions schedule-only change. The scraper entrypoints, queue logic, shard counts, route inventory, scrape horizon, and time budgets remain unchanged; only workflow `schedule` entries and matching tests/docs change.

**Tech Stack:** GitHub Actions YAML, Python pytest, PyYAML workflow parsing tests, Ruff.

## Global Constraints

- Add one scheduled daily run slot for Alaska and Delta only.
- Alaska schedule must become exactly `17 1,7,13,19 * * *`.
- Delta schedule must become exactly `0 2 * * *`, `0 8 * * *`, and `0 20 * * *`.
- JetBlue must remain exactly `37 2,14,20 * * *`.
- Do not change shard counts: Alaska remains 5, Delta remains 7, JetBlue remains 5.
- Do not change route inventory, scrape horizon, time budgets, entrypoint code, or queue logic.
- Keep documentation consistent with workflow schedules and the documented 20-job concurrency ceiling.

---

### Task 1: Add Alaska and Delta Run Slots

**Files:**
- Modify: `.github/workflows/alaska-scrape.yml`
- Modify: `.github/workflows/delta-browser-scrape.yml`
- Modify: `tests/test_alaska_scrape.py`
- Modify: `tests/test_delta_browser_scrape.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Existing workflow `on.schedule` cron entries and existing scraper matrix/env shard settings.
- Produces: Workflows with one additional daily schedule slot for Alaska and Delta, plus tests/docs that lock the intended schedules.

- [ ] **Step 1: Add failing schedule tests**

  Add an Alaska schedule test to `tests/test_alaska_scrape.py`:

  ```python
  def test_alaska_workflow_runs_four_times_daily_with_safe_spacing():
      with open(_WF) as f:
          wf = yaml.safe_load(f)
      schedule = wf[True]["schedule"]
      crons = [s["cron"] for s in schedule]
      assert crons == ["17 1,7,13,19 * * *"]
      hours = [int(h) for h in crons[0].split()[1].split(",")]
      assert hours == [1, 7, 13, 19]
      assert all(not (8 <= h <= 11) for h in hours), "Alaska must avoid the 08-11 UTC browser block"
  ```

  Add a Delta schedule test to `tests/test_delta_browser_scrape.py`:

  ```python
  def test_delta_workflow_runs_three_times_daily_with_safe_spacing():
      with open(_WF) as f:
          wf = yaml.safe_load(f)
      schedule = wf[True]["schedule"]
      crons = [s["cron"] for s in schedule]
      assert crons == ["0 2 * * *", "0 8 * * *", "0 20 * * *"]
      hours = [int(c.split()[1]) for c in crons]
      assert hours == [2, 8, 20]
  ```

- [ ] **Step 2: Run targeted tests and verify they fail**

  Run:

  ```bash
  pytest tests/test_alaska_scrape.py tests/test_delta_browser_scrape.py -q
  ```

  Expected: the new schedule tests fail because Alaska still has `17 1,13,19 * * *` and Delta still has only `0 8 * * *` / `0 20 * * *`.

- [ ] **Step 3: Update Alaska workflow schedule**

  In `.github/workflows/alaska-scrape.yml`, change the schedule to:

  ```yaml
  schedule:
    # 4x/day, offset to :17 and clear of the 08-11 UTC award-browser block. Alaska keeps
    # 5 shards and adds a 07:17 UTC run to reduce due-route queue wait.
    - cron: "17 1,7,13,19 * * *"
  ```

- [ ] **Step 4: Update Delta workflow schedule**

  In `.github/workflows/delta-browser-scrape.yml`, change the schedule block to:

  ```yaml
  schedule:
    - cron: "0 2 * * *"   # 3rd daily run adds queue-drain capacity without stacking on cash/JetBlue
    - cron: "0 8 * * *"   # daily at 08:00 UTC (clear of transfer-bonuses 09:00)
    - cron: "0 20 * * *"  # evening run halves Delta's effective TTL
  ```

  Update the header comment so it says Delta runs 7 shards and 3 scheduled slots.

- [ ] **Step 5: Update README**

  Update these README areas:

  - Delta job row schedule: `3x/day (02:00, 08:00, 20:00 UTC) + on-demand dispatch`.
  - Alaska job row schedule: `4x/day (01:17, 07:17, 13:17, 19:17 UTC)`.
  - Coverage-expansion concurrency note:

    ```text
    Alaska 01:17/07:17/13:17/19:17 x5, JetBlue 02:37/14:37/20:37 x5, Cash 06:15/14:15/22:15 x6,
    Delta 02:00/08:00/20:00 x7, Southwest 09:00 x6, Turkish 10:00 x3, Etihad 11:00 x2
    ```

  - Planned peak overlap should say roughly `17 jobs`, still under the 20-job ceiling.

- [ ] **Step 6: Run targeted tests and lint**

  Run:

  ```bash
  pytest tests/test_alaska_scrape.py tests/test_delta_browser_scrape.py -q
  ruff check .
  ```

  Expected: targeted tests pass and Ruff reports no findings.

- [ ] **Step 7: Run full test suite**

  Run:

  ```bash
  pytest tests/ -q
  ```

  Expected: full suite passes.

- [ ] **Step 8: Commit**

  Run:

  ```bash
  git add .github/workflows/alaska-scrape.yml .github/workflows/delta-browser-scrape.yml tests/test_alaska_scrape.py tests/test_delta_browser_scrape.py README.md
  git commit -m "ci: add alaska and delta run slots"
  ```
