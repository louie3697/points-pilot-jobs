# JetBlue Probe Backoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce JetBlue scheduled scrape pressure from one route across a 90-day horizon to one route for one date while keeping daily probe visibility.

**Architecture:** This is a workflow-configuration backoff only. The existing `jetblue_scrape.py` path already reads `JETBLUE_SCRAPE_DAYS`, and `browser_scrape_common.dense_sparse_dates()` already produces a single travel date when that value is `1`.

**Tech Stack:** GitHub Actions YAML, Python pytest, PyYAML, README documentation.

## Global Constraints

- Work only inside `/Users/louisn/Documents/indiehax/point_pilot/jobs/.worktrees/jetblue-probe-backoff`.
- Do not change scraper runtime logic for this task.
- Keep JetBlue scheduled at one daily cron: `37 20 * * *`.
- Keep JetBlue scheduled at one shard: matrix `shard: [0]`, `JETBLUE_SHARDS: "1"`.
- Keep JetBlue scheduled at one queued route: `JETBLUE_MAX_LEGS_PER_SHARD: "1"`.
- Change JetBlue scheduled horizon to one date: `JETBLUE_SCRAPE_DAYS: "1"`.
- Update tests and README so they match the live workflow behavior.
- Use TDD: update the test first, verify the focused test fails, then update workflow/docs.

---

### Task 1: Back Off JetBlue Scheduled Probe Horizon

**Files:**
- Modify: `.github/workflows/jetblue-scrape.yml`
- Modify: `tests/test_jetblue_scrape.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `jetblue_scrape.SCRAPE_DAYS` reads the `JETBLUE_SCRAPE_DAYS` environment variable.
- Produces: A scheduled workflow that logs one route by one date in cron mode.

- [ ] **Step 1: Write the failing workflow test**

In `tests/test_jetblue_scrape.py`, update `test_jetblue_workflow_shard_matrix_is_consistent` so it also asserts:

```python
    assert env["JETBLUE_SCRAPE_DAYS"] == "1"
```

Update the docstring and assertion message to say JetBlue uses a one-route, one-date daily probe while HTTP 406 blocked.

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
pytest tests/test_jetblue_scrape.py::test_jetblue_workflow_shard_matrix_is_consistent -q
```

Expected: FAIL because the workflow still has `JETBLUE_SCRAPE_DAYS: "90"`.

- [ ] **Step 3: Update the workflow probe horizon**

In `.github/workflows/jetblue-scrape.yml`, replace the current 90-day comment and value with:

```yaml
          # One-date canary while JetBlue returns HTTP 406: keep daily visibility without enough
          # consecutive blocked responses to trip the run-level circuit breaker.
          JETBLUE_SCRAPE_DAYS: "1"
```

Leave the cron, shard matrix, `JETBLUE_SHARDS`, `JETBLUE_MAX_LEGS_PER_SHARD`, and `JETBLUE_SHARD_INDEX` unchanged.

- [ ] **Step 4: Update README JetBlue notes**

In `README.md`, change the JetBlue table row from the old 3-times-daily, 5-shard description to one daily probe at `20:37 UTC`, one shard, one route, one date.

In the coverage-expansion HTML comment, change the JetBlue entry from the old 3-slot x5 note to `JetBlue 20:37 x1 one-date probe`.

In the "httpx scrapers" paragraph, change text claiming Alaska and JetBlue both use 5 shards so it says Alaska uses 5 shards and JetBlue is temporarily in a one-shard, one-date daily probe while HTTP 406 blocked.

- [ ] **Step 5: Run focused verification**

Run:

```bash
pytest tests/test_jetblue_scrape.py -q
```

Expected: PASS, with only the known local pyenv `hashlib` warning noise allowed.

- [ ] **Step 6: Run repo verification**

Run:

```bash
pytest tests/ -q
ruff check .
```

Expected: both commands exit 0.

- [ ] **Step 7: Commit**

Run:

```bash
git add .github/workflows/jetblue-scrape.yml tests/test_jetblue_scrape.py README.md docs/superpowers/specs/2026-07-05-jetblue-probe-backoff-design.md docs/superpowers/plans/2026-07-05-jetblue-probe-backoff.md
git commit -m "ci: reduce jetblue probe horizon"
```

Include this trailer in the commit message:

```text
Co-Authored-By: Codex <codex@openai.com>
```
