# Blocked Scraper Backoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put JetBlue and Southwest scheduled scrapers into low-volume probe mode while both are actively blocked.

**Architecture:** This is a workflow/config-only throttle. GitHub Actions matrix size, schedule, and env-overridden per-shard route caps control scheduled volume; scraper code and queue semantics stay unchanged.

**Tech Stack:** GitHub Actions YAML, Python workflow tests with PyYAML, existing `config.settings.CRON_MAX_LEGS_PER_SHARD` env override behavior.

## Global Constraints

- Do not remove workflow dispatch.
- Do not delete routes from `pp.routes_queue`.
- Do not change parser logic, block detection, queue scoring, or adaptive cadence.
- JetBlue scheduled probe mode must run once daily, with one shard and one queued route maximum.
- Southwest scheduled probe mode must run once daily, with one shard, one queued route maximum, and `SOUTHWEST_SCRAPE_DAYS=30`.
- No new dependencies.
- Run `pytest tests/test_jetblue_scrape.py tests/test_southwest_sharding.py tests/test_southwest_browser_scrape.py tests/test_settings_phase3.py -q`, then `pytest tests/ -q`, then `ruff check .`.

---

### Task 1: Throttle JetBlue and Southwest Scheduled Scrapers

**Files:**
- Modify: `.github/workflows/jetblue-scrape.yml`
- Modify: `.github/workflows/southwest-browser-scrape.yml`
- Modify: `tests/test_jetblue_scrape.py`
- Modify: `tests/test_southwest_sharding.py`
- Modify: `tests/test_southwest_browser_scrape.py`
- Modify: `tests/test_settings_phase3.py`

**Interfaces:**
- Consumes: env-overridable `CRON_MAX_LEGS_PER_SHARD` in `config/settings.py`
- Produces: workflows that set `JETBLUE_MAX_LEGS_PER_SHARD=1` and `SOUTHWEST_MAX_LEGS_PER_SHARD=1`

- [ ] **Step 1: Update JetBlue tests first**

In `tests/test_jetblue_scrape.py`, change the schedule test to expect one daily probe outside the 08-11 UTC block:

```python
def test_jetblue_workflow_runs_daily_probe_while_blocked():
    """JetBlue is currently 100% blocked on GitHub Actions HTTP 406, so keep a daily low-rate
    health probe instead of three 5-shard coverage pushes."""
    with open(_WF) as f:
        wf = yaml.safe_load(f)
    schedule = wf[True]["schedule"]
    crons = [s["cron"] for s in schedule]
    assert crons == ["37 20 * * *"]
    hour = int(crons[0].split()[1])
    assert not (8 <= hour <= 11), "cron must avoid the 08-11 UTC award block"
```

Change the shard matrix test to expect one shard and one queued route maximum:

```python
def test_jetblue_workflow_shard_matrix_is_consistent():
    """JetBlue stays in one-shard probe mode while 406 blocks are 100%."""
    with open(_WF) as f:
        wf = yaml.safe_load(f)
    job = wf["jobs"]["scrape"]
    shards = job["strategy"]["matrix"]["shard"]
    env = job["steps"][-1]["env"]
    n = int(env["JETBLUE_SHARDS"])
    assert shards == list(range(n)), f"matrix {shards} must be range(JETBLUE_SHARDS={n})"
    assert n == 1, "JetBlue runs one daily probe shard while HTTP 406 blocked"
    assert env["JETBLUE_MAX_LEGS_PER_SHARD"] == "1"
    assert env["JETBLUE_SHARD_INDEX"] == "${{ matrix.shard }}"
```

- [ ] **Step 2: Update Southwest tests first**

In `tests/test_southwest_sharding.py`, change the workflow matrix assertion:

```python
def test_southwest_workflow_shard_matrix_is_consistent():
    with open(_WF) as f:
        wf = yaml.safe_load(f)
    job = wf["jobs"]["scrape"]
    shards = job["strategy"]["matrix"]["shard"]
    env = job["steps"][-1]["env"]
    n = int(env["SOUTHWEST_SHARDS"])
    assert shards == list(range(n)), f"matrix {shards} must be range(SOUTHWEST_SHARDS={n})"
    assert n == 1, "Southwest runs one daily probe shard while 403 blocked"
    assert env["SOUTHWEST_MAX_LEGS_PER_SHARD"] == "1"
    assert env["SOUTHWEST_SCRAPE_DAYS"] == "30"
    assert env["SOUTHWEST_SHARD_INDEX"] == "${{ matrix.shard }}"
```

In `tests/test_southwest_browser_scrape.py`, update the dense/sparse horizon test to pin `SCRAPE_DAYS=30` and expect a shorter horizon:

```python
def test_southwest_cron_uses_dense_sparse_horizon(monkeypatch):
    """Probe mode keeps a 30d horizon while Southwest is 403-blocked."""
    import southwest_browser_scrape as ep

    captured = {}
    monkeypatch.setattr(
        ep.common, "build_queue_plan", lambda *a, **k: (["JOB"], ["IGNORED_DATE"])
    )
    monkeypatch.setattr(
        ep.common, "run_scrape",
        lambda scraper, pairs, dates, **kw: captured.update(dates=dates) or 0,
    )
    monkeypatch.setattr("scrapers.southwest.SouthwestScraper", _StubScraper)

    today = date(2026, 6, 25)
    monkeypatch.setattr(ep, "date", _FixedDate(today))
    monkeypatch.setattr(ep, "SCRAPE_DAYS", 30)

    ep._run_cron(shard_index=0, shards=1)

    dates = captured["dates"]
    offsets = sorted((d - today).days for d in dates)
    assert dates != ["IGNORED_DATE"]
    assert offsets[:3] == [0, 1, 2]
    assert 25 <= offsets[-1] < 30
    assert len(dates) <= 12
```

In `tests/test_settings_phase3.py`, keep default settings unchanged because the backoff is workflow-env scoped:

```python
assert CRON_MAX_LEGS_PER_SHARD["southwest"] == 20
```

Add a comment near that assertion if needed that workflow env overrides scheduled probe mode.

- [ ] **Step 3: Run focused tests and confirm failure**

Run:

```bash
pytest tests/test_jetblue_scrape.py tests/test_southwest_sharding.py tests/test_southwest_browser_scrape.py tests/test_settings_phase3.py -q
```

Expected: fails until workflow YAML is updated.

- [ ] **Step 4: Update JetBlue workflow**

In `.github/workflows/jetblue-scrape.yml`:

- Replace the schedule comment with a blocked-probe comment.
- Change cron to:

```yaml
    - cron: "37 20 * * *"
```

- Change matrix to:

```yaml
        shard: [0]
```

- Change env to:

```yaml
          JETBLUE_SHARDS: "1"
          JETBLUE_MAX_LEGS_PER_SHARD: "1"
```

Keep `JETBLUE_SCRAPE_DAYS: "90"`.

- [ ] **Step 5: Update Southwest workflow**

In `.github/workflows/southwest-browser-scrape.yml`:

- Replace the shard/backoff comments with blocked-probe wording.
- Change matrix to:

```yaml
        shard: [0]
```

- Change env to:

```yaml
          SOUTHWEST_SCRAPE_DAYS: "30"
          SOUTHWEST_SHARDS: "1"
          SOUTHWEST_MAX_LEGS_PER_SHARD: "1"
```

Keep the daily `0 9 * * *` schedule.

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest tests/test_jetblue_scrape.py tests/test_southwest_sharding.py tests/test_southwest_browser_scrape.py tests/test_settings_phase3.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Run full checks**

Run:

```bash
pytest tests/ -q
ruff check .
```

Expected: tests pass and ruff reports no findings.

- [ ] **Step 8: Commit**

Run:

```bash
git add .github/workflows/jetblue-scrape.yml .github/workflows/southwest-browser-scrape.yml tests/test_jetblue_scrape.py tests/test_southwest_sharding.py tests/test_southwest_browser_scrape.py tests/test_settings_phase3.py
git commit -m "ci: back off blocked JetBlue and Southwest scrapers"
```
