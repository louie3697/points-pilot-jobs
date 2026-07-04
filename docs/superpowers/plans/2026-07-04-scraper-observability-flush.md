# Scraper Observability Flush Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure scraper completion metrics/logs flush before every scraper hard-exit.

**Architecture:** Add a single `pipeline.obs.flush_then_hard_exit()` helper and route every scraper entrypoint that currently calls `os._exit(0)` through it. Tests cover the helper's sleep/flush/exit ordering and the entrypoint source contract.

**Tech Stack:** Python, pytest, existing `pipeline.obs` asynchronous Better Stack shipper, GitHub Actions scraper entrypoints.

## Global Constraints

- Do not change scrape behavior, queue behavior, budgets, route selection, or heartbeat semantics.
- Existing nodriver browser scrapers must preserve the 3-second delay before hard exit.
- Alaska and JetBlue hard-exit entrypoints must flush without adding an artificial delay.
- No new dependencies.
- Use TDD and run `pytest tests/ test_obs.py -q` plus `ruff check .`.

---

### Task 1: Flush Before Scraper Hard Exit

**Files:**
- Modify: `pipeline/obs.py`
- Modify: `cash_browser_scrape.py`
- Modify: `delta_browser_scrape.py`
- Modify: `etihad_browser_scrape.py`
- Modify: `southwest_browser_scrape.py`
- Modify: `turkish_browser_scrape.py`
- Modify: `alaska_scrape.py`
- Modify: `jetblue_scrape.py`
- Test: `tests/test_scraper_observability_exit.py`

**Interfaces:**
- Consumes: existing `pipeline.obs.flush(timeout: float = 5.0) -> None`
- Produces: `pipeline.obs.flush_then_hard_exit(code: int = 0, *, delay_s: float = 0.0) -> None`

- [ ] **Step 1: Write failing helper and entrypoint tests**

Create `tests/test_scraper_observability_exit.py`:

```python
from pathlib import Path

import pytest

import pipeline.obs as obs


def test_flush_then_hard_exit_sleeps_flushes_then_exits(monkeypatch):
    events = []

    monkeypatch.setattr(obs.time, "sleep", lambda seconds: events.append(("sleep", seconds)))
    monkeypatch.setattr(obs, "flush", lambda: events.append(("flush", None)))

    def fake_exit(code):
        events.append(("exit", code))
        raise SystemExit(code)

    monkeypatch.setattr(obs.os, "_exit", fake_exit)

    with pytest.raises(SystemExit) as exc:
        obs.flush_then_hard_exit(7, delay_s=3.0)

    assert exc.value.code == 7
    assert events == [("sleep", 3.0), ("flush", None), ("exit", 7)]


def test_flush_then_hard_exit_skips_sleep_when_delay_is_zero(monkeypatch):
    events = []

    monkeypatch.setattr(obs.time, "sleep", lambda seconds: events.append(("sleep", seconds)))
    monkeypatch.setattr(obs, "flush", lambda: events.append(("flush", None)))

    def fake_exit(code):
        events.append(("exit", code))
        raise SystemExit(code)

    monkeypatch.setattr(obs.os, "_exit", fake_exit)

    with pytest.raises(SystemExit):
        obs.flush_then_hard_exit()

    assert events == [("flush", None), ("exit", 0)]


def test_scraper_hard_exit_entrypoints_use_flush_helper():
    root = Path(__file__).resolve().parents[1]
    expected = {
        "cash_browser_scrape.py": "flush_then_hard_exit(delay_s=3.0)",
        "delta_browser_scrape.py": "flush_then_hard_exit(delay_s=3.0)",
        "etihad_browser_scrape.py": "flush_then_hard_exit(delay_s=3.0)",
        "southwest_browser_scrape.py": "flush_then_hard_exit(delay_s=3.0)",
        "turkish_browser_scrape.py": "flush_then_hard_exit(delay_s=3.0)",
        "alaska_scrape.py": "flush_then_hard_exit()",
        "jetblue_scrape.py": "flush_then_hard_exit()",
    }

    for relpath, call in expected.items():
        text = (root / relpath).read_text()
        assert call in text
        assert "os._exit(0)" not in text
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
pytest tests/test_scraper_observability_exit.py -q
```

Expected: fails because `pipeline.obs.flush_then_hard_exit` does not exist and entrypoints still call `os._exit(0)` directly.

- [ ] **Step 3: Implement helper**

In `pipeline/obs.py`, import `os` and add below `flush()`:

```python
def flush_then_hard_exit(code: int = 0, *, delay_s: float = 0.0) -> None:
    """Flush Better Stack POST threads before hard-exiting scraper entrypoints.

    Some browser libraries leave non-daemon teardown tasks alive after successful scrapes.
    The scraper entrypoints intentionally hard-exit to avoid hanging GitHub Actions jobs, but
    metrics/logs are shipped on daemon threads and can be lost unless they are flushed first.
    """
    if delay_s > 0:
        time.sleep(delay_s)
    flush()
    os._exit(code)
```

- [ ] **Step 4: Wire entrypoints**

Replace each direct hard-exit block:

```python
time.sleep(3)
os._exit(0)
```

with:

```python
from pipeline.obs import flush_then_hard_exit

flush_then_hard_exit(delay_s=3.0)
```

For `alaska_scrape.py` and `jetblue_scrape.py`, replace direct `os._exit(0)` with:

```python
from pipeline.obs import flush_then_hard_exit

flush_then_hard_exit()
```

Remove now-unused `time` imports from entrypoints that only used it for the exit sleep. Keep `os` imports where env parsing still uses `os`.

- [ ] **Step 5: Run focused tests**

Run:

```bash
pytest tests/test_scraper_observability_exit.py test_obs.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Run full checks**

Run:

```bash
pytest tests/ test_obs.py -q
ruff check .
```

Expected: tests pass and ruff reports no findings.

- [ ] **Step 7: Commit**

Run:

```bash
git add pipeline/obs.py cash_browser_scrape.py delta_browser_scrape.py etihad_browser_scrape.py southwest_browser_scrape.py turkish_browser_scrape.py alaska_scrape.py jetblue_scrape.py tests/test_scraper_observability_exit.py
git commit -m "fix: flush scraper observability before hard exit"
```
