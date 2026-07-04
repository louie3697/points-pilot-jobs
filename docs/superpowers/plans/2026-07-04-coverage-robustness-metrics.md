# Coverage Robustness Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve scraper density and observability using the July 4 coverage report and queue/log metrics.

**Architecture:** Keep scraper topology unchanged, then tune capacity where the live data shows headroom. Add one shared award metric field so Better Stack can distinguish productive green runs from zero-yield green runs.

**Tech Stack:** Python 3.11, pytest, ruff, GitHub Actions workflow YAML, existing `browser_scrape_common.run_scrape`.

## Global Constraints

- Work only inside `/Users/louisn/Documents/indiehax/point_pilot/.worktrees/jobs-coverage-robustness`.
- Do not add new routes in this pass.
- Keep the existing 3 daily Delta slots and 7 Delta shards.
- Keep the existing 3 daily cash slots and 6 cash shards.
- Delta workflow must set `CRON_TIME_BUDGET_S` to `7200`.
- Cash workflow must set `CASH_SCRAPE_DAYS` to `45`.
- Award `scrape_run` metrics must include `routes_zero`.
- Do not make zero-record, non-blocked award routes fail or skip adaptive marking.
- Run `pytest tests/ -q` and `ruff check .` before reporting done.

---

### Task 1: Add Zero-Route Award Metric And Clarify Budget Logs

**Files:**
- Modify: `browser_scrape_common.py`
- Test: `tests/test_browser_scrape_budget.py`

**Interfaces:**
- Consumes: existing `run_scrape(scraper, pairs, dates, ..., route_jobs=None, time_budget_s=None) -> int`
- Produces: `scrape_run` metric payload gains integer `routes_zero`

- [ ] **Step 1: Write failing tests for `routes_zero`**

Add this test to `tests/test_browser_scrape_budget.py`:

```python
def test_run_scrape_metric_counts_zero_record_routes(monkeypatch):
    metrics = _stub_io(monkeypatch)
    scraper = _FakeScraper()

    common.run_scrape(
        scraper,
        [("SEA", "JFK"), ("LAX", "BOS")],
        [date(2026, 7, 1)],
        source="jetblue",
        service="point-pilot-jetblue",
        airline="B6",
        heartbeat_url="",
        logger=logging.getLogger("t"),
        time_budget_s=3600,
    )

    assert scraper.calls == 2
    assert metrics[0]["routes_scraped"] == 2
    assert metrics[0]["routes_zero"] == 2
```

Also extend `test_run_scrape_queue_mode_blocked_route_sets_backoff_and_metric_fields` with:

```python
assert metrics[0]["routes_zero"] == 0
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```bash
pytest tests/test_browser_scrape_budget.py -q
```

Expected: the new test fails with `KeyError: 'routes_zero'`.

- [ ] **Step 3: Implement `routes_zero` and clearer budget warning**

In `browser_scrape_common.py`, initialize `routes_zero = 0` beside the other counters:

```python
total = error_count = routes_scraped = routes_unchanged = routes_zero = 0
```

In the time-budget warning, use the assigned-route count and backlog count:

```python
assigned_count = len(iterable)
logger.warning(
    "time budget %.0fs reached after %d/%d assigned routes "
    "(%d total due backlog) — stopping cleanly (unreached routes stay due)",
    budget_s,
    routes_scraped,
    assigned_count,
    due_count,
)
```

After `routes_scraped += 1`, count zero-record non-blocked routes:

```python
if not route_recs:
    routes_zero += 1
```

In the metric payload, add:

```python
"routes_zero": routes_zero,
```

- [ ] **Step 4: Run the focused test and confirm it passes**

Run:

```bash
pytest tests/test_browser_scrape_budget.py -q
```

Expected: all tests in the file pass.

### Task 2: Tune Delta Time Budget And Cash Horizon

**Files:**
- Modify: `.github/workflows/delta-browser-scrape.yml`
- Modify: `.github/workflows/cash-browser-scrape.yml`
- Test: `tests/test_delta_browser_scrape.py`
- Test: `tests/test_cash_workflow.py`

**Interfaces:**
- Produces: Delta workflow env includes `CRON_TIME_BUDGET_S: "7200"`
- Produces: Cash workflow env has `CASH_SCRAPE_DAYS: "45"`

- [ ] **Step 1: Write failing workflow tests**

In `tests/test_delta_browser_scrape.py`, extend `test_delta_workflow_shard_matrix_is_consistent` with:

```python
assert env["CRON_TIME_BUDGET_S"] == "7200"
```

In `tests/test_cash_workflow.py`, update the final assertion in `test_cash_workflow_shards_and_route_limit_are_consistent`:

```python
assert env["CASH_SCRAPE_DAYS"] == "45"
```

- [ ] **Step 2: Run focused tests and confirm they fail**

Run:

```bash
pytest tests/test_delta_browser_scrape.py tests/test_cash_workflow.py -q
```

Expected: Delta fails because `CRON_TIME_BUDGET_S` is missing and cash fails because the workflow still says `30`.

- [ ] **Step 3: Update workflow env**

In `.github/workflows/delta-browser-scrape.yml`, add this env var next to `DELTA_SCRAPE_DAYS`:

```yaml
          CRON_TIME_BUDGET_S: "7200"
```

In `.github/workflows/cash-browser-scrape.yml`, change:

```yaml
          CASH_SCRAPE_DAYS: "30"
```

to:

```yaml
          CASH_SCRAPE_DAYS: "45"
```

- [ ] **Step 4: Run focused tests and confirm they pass**

Run:

```bash
pytest tests/test_delta_browser_scrape.py tests/test_cash_workflow.py -q
```

Expected: all focused workflow tests pass.

### Task 3: Full Jobs Validation

**Files:**
- No additional source files.

**Interfaces:**
- Produces: green jobs repo checks and a concise implementation report.

- [ ] **Step 1: Run unit tests**

Run:

```bash
pytest tests/ -q
```

Expected: all tests pass. Known local `hashlib`/`blake2` warnings may appear before pytest output.

- [ ] **Step 2: Run lint**

Run:

```bash
ruff check .
```

Expected: no lint violations.

- [ ] **Step 3: Inspect diff**

Run:

```bash
git diff --check
git diff --stat
```

Expected: no whitespace errors; changed files are limited to the two workflows, shared runner/test files, and this spec/plan if already present.

- [ ] **Step 4: Report**

Write `/Users/louisn/Documents/indiehax/point_pilot/.worktrees/jobs-coverage-robustness/.superpowers/sdd/task-implementation-report.md` containing:

```markdown
# Coverage Robustness Metrics Report

## Status
DONE

## Changes
- Added `routes_zero` to award `scrape_run` metrics.
- Clarified time-budget warning text.
- Set Delta `CRON_TIME_BUDGET_S=7200`.
- Set cash `CASH_SCRAPE_DAYS=45`.

## Tests
- `pytest tests/ -q`
- `ruff check .`
- `git diff --check`

## Notes
- Do not claim JetBlue/Southwest/Turkish are fixed by this pass; they remain follow-up scraper repairs.
```
