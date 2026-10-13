# Monthly Blocked-Carrier Probes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Reduce scheduled Delta, JetBlue, and Turkish work to monthly probes.

**Architecture:** Edit the three existing workflow schedules, their existing tests, and schedule documentation. No runtime behavior changes.

**Tech Stack:** GitHub Actions YAML, Python/pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-10-12-monthly-blocked-probes-design.md`

## Global Constraints

- Monthly on day 1: Delta `0 8 1 * *`, Turkish `0 10 1 * *`, JetBlue `37 20 1 * *`.
- Preserve manual dispatch and inputs, concurrency, permissions, containers, one-shard/one-route/one-date limits, and other workflows.
- Modify existing schedule tests; add no new dependencies or runtime code.
- Do not trigger known-blocked scrapes to validate cron edits.

## Review Focus

- YAML parses `on` as `True` with PyYAML's default loader; use existing test conventions.
- Monthly means day-of-month 1 and any weekday, not Sunday plus day 1.
- Manual dispatch remains usable independently of schedule.
- Existing probe limits must remain one route/date/shard.
- README and workflow comments must describe monthly cadence accurately.

### Task 1: Reduce the three schedules and align existing documentation/tests

**Files:**
- Modify `.github/workflows/delta-browser-scrape.yml`, `.github/workflows/jetblue-scrape.yml`, `.github/workflows/turkish-browser-scrape.yml`.
- Modify `tests/test_delta_browser_scrape.py`, `tests/test_jetblue_scrape.py`, `tests/test_turkish_browser_scrape.py`.
- Modify `README.md` and directly affected workflow comments.

**Interfaces:** Consumes existing GitHub cron schedules; produces the monthly schedules specified in Global Constraints.

- [ ] Check the baseline using a working Python environment. The pre-existing health-jobs venv currently fails before test collection due to a missing libintl library; use Homebrew Python with a worktree-local `.venv` if needed. Run `python -m pip install -r requirements.txt` and install Ruff for local validation only.
- [ ] Update existing schedule assertions and their descriptive names/docstrings to expect the exact new cron values. Keep existing assertions for manual dispatch and one-shard/route/date budgets. Run `python -m pytest tests/test_delta_browser_scrape.py tests/test_jetblue_scrape.py tests/test_turkish_browser_scrape.py -q` and capture expected schedule failures before editing workflows.
- [ ] Change only the cron expressions and matching cadence text in workflows/README/tests. Delta becomes `0 8 1 * *`, Turkish `0 10 1 * *`, JetBlue `37 20 1 * *`.
- [ ] Run the focused set, then `python -m pytest tests/ -q`, `python -m ruff check .`, and `git diff --check`. If lint has unrelated baseline failures, report exact baseline evidence and run touched-file lint without unrelated changes. There is no configured type-check command in this Python repository; record that rather than invent one.
- [ ] Self-review, commit with explicit file adds and `Co-Authored-By: Codex <codex@openai.com>`, and write the required report. Do not push, open PRs, merge, deploy, or spawn subagents.

The controller reviews the result, opens and immediately squash-merges the PR per repository instructions, verifies the remote main content and active workflow state, and removes the feature worktree after merge.
