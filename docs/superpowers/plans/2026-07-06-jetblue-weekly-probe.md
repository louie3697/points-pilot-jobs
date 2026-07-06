# JetBlue Weekly Probe Backoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change JetBlue scheduled probing from daily to weekly while preserving the one-shard, one-route, one-date canary and manual dispatch.

**Architecture:** This is a GitHub Actions cadence/configuration change only. The scraper runtime stays unchanged; existing env values keep each scheduled run to one route and one date.

**Tech Stack:** GitHub Actions YAML, Python pytest, PyYAML, README documentation.

## Global Constraints

- Work only inside `/Users/louisn/Documents/indiehax/point_pilot/jobs/.worktrees/jetblue-weekly-probe`.
- Do not change scraper runtime logic for this task.
- Keep `workflow_dispatch`.
- Change JetBlue scheduled cron from daily `37 20 * * *` to weekly Sunday `37 20 * * 0`.
- Keep JetBlue scheduled at one shard: matrix `shard: [0]`, `JETBLUE_SHARDS: "1"`.
- Keep JetBlue scheduled at one queued route: `JETBLUE_MAX_LEGS_PER_SHARD: "1"`.
- Keep JetBlue scheduled horizon at one date: `JETBLUE_SCRAPE_DAYS: "1"`.
- Update tests and README so they match the live workflow behavior.
- Use TDD: update the test first, verify the focused test fails, then update workflow/docs.

---

### Task 1: Change JetBlue Canary Cadence To Weekly

**Files:**
- Modify: `.github/workflows/jetblue-scrape.yml`
- Modify: `tests/test_jetblue_scrape.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: GitHub Actions cron syntax.
- Produces: A weekly scheduled JetBlue canary plus unchanged manual dispatch.

- [ ] **Step 1: Write the failing workflow schedule test**

In `tests/test_jetblue_scrape.py`, rename `test_jetblue_workflow_runs_daily_probe_while_blocked` to:

```python
def test_jetblue_workflow_runs_weekly_probe_while_blocked():
```

Update its docstring to say JetBlue runs a weekly low-rate health probe while HTTP 406 remains blocked.

Change its cron assertion to:

```python
    assert crons == ["37 20 * * 0"]
```

Add explicit assertions for the weekly Sunday schedule:

```python
    minute, hour, _dom, _month, dow = crons[0].split()
    assert minute == "37"
    assert hour == "20"
    assert dow == "0"
```

Keep the check that the hour avoids the `08–11 UTC` award block.

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
pytest tests/test_jetblue_scrape.py::test_jetblue_workflow_runs_weekly_probe_while_blocked -q
```

Expected: FAIL because the workflow still has daily `37 20 * * *`.

- [ ] **Step 3: Update the workflow cron and comments**

In `.github/workflows/jetblue-scrape.yml`, update the schedule comment to:

```yaml
    # Weekly one-route/one-date canary while JetBlue returns HTTP 406. Manual dispatch stays
    # available for unblock checks without burning a known-failing scheduled request every day.
    - cron: "37 20 * * 0"
```

Leave `workflow_dispatch`, matrix `shard: [0]`, `JETBLUE_SHARDS`, `JETBLUE_MAX_LEGS_PER_SHARD`,
`JETBLUE_SHARD_INDEX`, and `JETBLUE_SCRAPE_DAYS` unchanged.

- [ ] **Step 4: Update README JetBlue notes**

In `README.md`, change the JetBlue table row schedule from `daily 20:37 UTC` to `weekly Sunday 20:37 UTC`.

In the coverage-expansion HTML comment, change `JetBlue 20:37 x1 one-date probe` to `JetBlue Sunday 20:37 x1 one-date probe`.

In the "httpx scrapers" paragraph, change `one-route, one-date daily probe` to `one-route, one-date weekly probe`.

In the generic sharding sentence, change `JetBlue 1-route/1-date (temporary probe)` to `JetBlue 1-route/1-date weekly (temporary probe)`.

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
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit**

Run:

```bash
git add .github/workflows/jetblue-scrape.yml tests/test_jetblue_scrape.py README.md
git commit -m "ci: reduce jetblue probe cadence"
```

Include this trailer in the commit message:

```text
Co-Authored-By: Codex <codex@openai.com>
```
