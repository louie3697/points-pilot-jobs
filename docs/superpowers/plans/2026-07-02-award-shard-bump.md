# Award Shard Bump Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one GitHub Actions matrix shard each to Alaska, Delta, and JetBlue award scrapers.

**Architecture:** This is a workflow-capacity change only. The existing cron entrypoints already read `<AIRLINE>_SHARDS` and `<AIRLINE>_SHARD_INDEX`; the workflows provide one more matrix index and a matching env value.

**Tech Stack:** GitHub Actions YAML, Python pytest, PyYAML workflow parsing tests, Ruff.

## Global Constraints

- This change must add one parallel shard per scheduled run, not another cron slot.
- Alaska must move from 4 to 5 shards with matrix `[0, 1, 2, 3, 4]`.
- Delta must move from 6 to 7 shards with matrix `[0, 1, 2, 3, 4, 5, 6]`.
- JetBlue must move from 4 to 5 shards with matrix `[0, 1, 2, 3, 4]`.
- Keep all existing cron schedules, scrape horizons, route lists, and entrypoint code unchanged.
- Keep workflow matrix values and `<AIRLINE>_SHARDS` env values exactly consistent.

---

### Task 1: Bump Award Workflow Shards

**Files:**
- Modify: `.github/workflows/alaska-scrape.yml`
- Modify: `.github/workflows/delta-browser-scrape.yml`
- Modify: `.github/workflows/jetblue-scrape.yml`
- Modify: `tests/test_alaska_scrape.py`
- Modify: `tests/test_delta_browser_scrape.py`
- Modify: `tests/test_jetblue_scrape.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Existing workflow matrix sharding contract: matrix values are passed as `<AIRLINE>_SHARD_INDEX`, and `<AIRLINE>_SHARDS` tells the entrypoint the stride length.
- Produces: Workflows whose matrices and env shard counts are exactly consistent and documented.

- [ ] **Step 1: Write failing test assertions for the new minimum shard counts**

  Update the workflow tests so they require the new exact shard counts, not only prior lower bounds:

  ```python
  # tests/test_alaska_scrape.py
  assert n == 5, "Alaska runs 5 fresh-IP shards after the July 2026 queue-drain bump"
  ```

  ```python
  # tests/test_delta_browser_scrape.py
  assert n == 7, "Delta runs 7 fresh-IP shards after the July 2026 queue-drain bump"
  ```

  ```python
  # tests/test_jetblue_scrape.py
  assert n == 5, "JetBlue runs 5 fresh-IP shards after the July 2026 queue-drain bump"
  ```

- [ ] **Step 2: Run targeted tests and verify they fail**

  Run:

  ```bash
  pytest tests/test_alaska_scrape.py tests/test_delta_browser_scrape.py tests/test_jetblue_scrape.py -q
  ```

  Expected: the three shard-count assertions fail because the workflows still declare Alaska 4, Delta 6, JetBlue 4.

- [ ] **Step 3: Update workflow matrices and env values**

  Change the workflow matrix and env count in each file:

  ```yaml
  # .github/workflows/alaska-scrape.yml
  matrix:
    shard: [0, 1, 2, 3, 4]
  ```

  ```yaml
  ALASKA_SHARDS: "5"
  ```

  ```yaml
  # .github/workflows/delta-browser-scrape.yml
  matrix:
    shard: [0, 1, 2, 3, 4, 5, 6]
  ```

  ```yaml
  DELTA_SHARDS: "7"
  ```

  ```yaml
  # .github/workflows/jetblue-scrape.yml
  matrix:
    shard: [0, 1, 2, 3, 4]
  ```

  ```yaml
  JETBLUE_SHARDS: "5"
  ```

- [ ] **Step 4: Update workflow comments and README**

  Keep comments concise and factual:

  - Alaska now runs 5 shards.
  - Delta now runs 7 shards.
  - JetBlue now runs 5 shards.
  - The coverage-expansion concurrency note should say planned peak overlap is roughly cash plus Delta, or 13 jobs.

- [ ] **Step 5: Run targeted tests and lint**

  Run:

  ```bash
  pytest tests/test_alaska_scrape.py tests/test_delta_browser_scrape.py tests/test_jetblue_scrape.py -q
  ruff check .
  ```

  Expected: all targeted tests pass, and Ruff reports no findings.

- [ ] **Step 6: Run full test suite**

  Run:

  ```bash
  pytest tests/ -q
  ```

  Expected: full suite passes.

- [ ] **Step 7: Commit**

  Run:

  ```bash
  git add .github/workflows/alaska-scrape.yml .github/workflows/delta-browser-scrape.yml .github/workflows/jetblue-scrape.yml tests/test_alaska_scrape.py tests/test_delta_browser_scrape.py tests/test_jetblue_scrape.py README.md
  git commit -m "ci: add award scraper shards"
  ```
