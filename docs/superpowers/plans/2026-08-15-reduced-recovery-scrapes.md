# Reduced Recovery Scrapes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound the Turkish scheduled recovery check to one route by one date and make repository
documentation match the already-reduced Delta, JetBlue, and Turkish schedules.

**Architecture:** This is a GitHub Actions configuration change. The existing settings loader
already consumes `TURKISH_MAX_LEGS_PER_SHARD`, so the workflow supplies the reduced matrix, shard
count, route cap, and date window. A YAML contract test prevents those coupled values from
drifting. Better Stack cadence corrections happen after merge as operational validation.

**Tech Stack:** GitHub Actions YAML, Python 3.11, pytest, PyYAML, Ruff, Better Stack.

**Spec:** `docs/superpowers/specs/2026-08-15-reduced-recovery-scrapes-design.md`

## Global Constraints

- Work only inside `/Users/louisn/Documents/indiehax/point_pilot/jobs/.worktrees/reduced-recovery-scrapes`.
- Do not change scraper runtime logic or healthy airline workflows.
- Keep Turkish scheduled daily at `0 10 * * *` and keep `workflow_dispatch`.
- Set Turkish to matrix `shard: [0]`, `TURKISH_SHARDS: "1"`,
  `TURKISH_MAX_LEGS_PER_SHARD: "1"`, and `TURKISH_SCRAPE_DAYS: "1"`.
- Keep `TURKISH_SHARD_INDEX: ${{ matrix.shard }}`.
- Correct README statements for Delta and Turkish without changing their intended behavior.
- Use TDD: add the workflow contract test first, run it red, then change workflow/docs.
- Run tests with `.venv311/bin/python` and lint with
  `.venv311/bin/ruff check . --force-exclude --extend-exclude .venv --extend-exclude .venv311`.
- Commit with `Co-Authored-By: Codex <codex@openai.com>`.

---

### Task 1: Reduce Turkish Scheduled Recovery Work

**Files:**
- Modify: `tests/test_turkish_browser_scrape.py`
- Modify: `.github/workflows/turkish-browser-scrape.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: GitHub Actions cron and workflow environment values.
- Produces: One daily Turkish recovery job capped at one queued route and one travel date, plus
  unchanged manual dispatch.

- [ ] **Step 1: Write the failing workflow contract test**

In `tests/test_turkish_browser_scrape.py`, import `yaml`, define:

```python
_WF = ".github/workflows/turkish-browser-scrape.yml"
```

Add `test_turkish_workflow_is_one_daily_recovery_probe` that loads `_WF` with `yaml.safe_load`,
accounts for PyYAML parsing bare `on:` as `True`, and asserts:

```python
assert [entry["cron"] for entry in wf[True]["schedule"]] == ["0 10 * * *"]
assert "workflow_dispatch" in wf[True]

job = wf["jobs"]["scrape"]
env = job["steps"][-1]["env"]
assert job["strategy"]["matrix"]["shard"] == [0]
assert env["TURKISH_SHARDS"] == "1"
assert env["TURKISH_MAX_LEGS_PER_SHARD"] == "1"
assert env["TURKISH_SCRAPE_DAYS"] == "1"
assert env["TURKISH_SHARD_INDEX"] == "${{ matrix.shard }}"
```

- [ ] **Step 2: Prove the test is red**

Run:

```bash
.venv311/bin/python -m pytest \
  tests/test_turkish_browser_scrape.py::test_turkish_workflow_is_one_daily_recovery_probe -q
```

Expected: FAIL because the workflow still declares three shards, five dates, and no Turkish route
cap.

- [ ] **Step 3: Reduce the workflow**

In `.github/workflows/turkish-browser-scrape.yml`:

- update the top-level description, blank-date input description, and job comments to describe a
  daily one-route/one-date recovery probe while the upstream response is unsuccessful;
- change matrix `shard` to `[0]`;
- set `TURKISH_SCRAPE_DAYS: "1"`;
- set `TURKISH_SHARDS: "1"`;
- add `TURKISH_MAX_LEGS_PER_SHARD: "1"` adjacent to the other Turkish scheduling values;
- leave the cron, manual inputs, secrets, shard-index mapping, and run command unchanged.

- [ ] **Step 4: Correct README operations documentation**

In `README.md`:

- change Delta's schedule from daily to weekly Sunday 08:00 UTC;
- describe Turkish as a daily one-shard, one-route, one-date recovery probe;
- update the concurrency comment from Turkish `x3` to `x1`;
- update the sharding paragraph so Delta, JetBlue, and Turkish all match their workflows;
- change the Delta heartbeat-secret description from daily to weekly.

- [ ] **Step 5: Run focused verification**

Run:

```bash
.venv311/bin/python -m pytest tests/test_turkish_browser_scrape.py -q
```

Expected: PASS.

- [ ] **Step 6: Run repository verification**

Run:

```bash
.venv311/bin/python -m pytest tests/ -q
.venv311/bin/ruff check . --force-exclude --extend-exclude .venv --extend-exclude .venv311
.venv311/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/turkish-browser-scrape.yml')); print('yaml ok')"
git diff --check
```

Expected: 276 existing tests plus the new test pass; Ruff, YAML parsing, and whitespace checks all
exit zero.

- [ ] **Step 7: Commit**

Run:

```bash
git add tests/test_turkish_browser_scrape.py .github/workflows/turkish-browser-scrape.yml README.md
git commit -m "ci: reduce turkish recovery scrape load" -m "Co-Authored-By: Codex <codex@openai.com>"
```
