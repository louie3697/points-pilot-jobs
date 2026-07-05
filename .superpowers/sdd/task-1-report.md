Task 1 Report — Back Off JetBlue Scheduled Probe Horizon

## What I implemented
- Updated `tests/test_jetblue_scrape.py::test_jetblue_workflow_shard_matrix_is_consistent` to assert
  `JETBLUE_SCRAPE_DAYS == "1"` and updated the docstring/message to describe the one-route, one-date daily
  probe while HTTP 406 is blocked.
- Updated `.github/workflows/jetblue-scrape.yml`:
  - Replaced the old 90-day comment with a canary comment for HTTP 406.
  - Changed `JETBLUE_SCRAPE_DAYS` from `"90"` to `"1"`.
  - Left cron, shard matrix, and other JetBlue env settings unchanged.
- Updated `README.md` JetBlue notes:
  - Jobs table now says `jetblue_scrape.py` runs daily at `20:37 UTC`, one shard (`shard: [0]`), one-route
    daily probe context.
  - Coverage-expansion comment now lists `JetBlue 20:37 x1 one-date probe`.
  - `httpx scrapers` paragraph now states Alaska is 5 shards and JetBlue is temporarily one-shard, one-route, one-date
    daily while blocked.

## Tests and exact results
- `pytest tests/test_jetblue_scrape.py::test_jetblue_workflow_shard_matrix_is_consistent -q`
  - Result: **FAIL** (expected) because `JETBLUE_SCRAPE_DAYS` was `"90"` before workflow update.
- `pytest tests/test_jetblue_scrape.py -q`
  - Result: **PASS** (3 passed).
- `pytest tests/ -q`
  - Result: **PASS** (241 passed, 8 skipped).
- `ruff check .`
  - Result: **PASS**.

## TDD Evidence

### RED
- Command:
```bash
pytest tests/test_jetblue_scrape.py::test_jetblue_workflow_shard_matrix_is_consistent -q
```
- Output excerpt:
```text
F                                                                        [100%]
=================================== FAILURES ===================================
E       AssertionError: JetBlue runs one date per scheduled probe while HTTP 406 blocked
E       assert '90' == '1'
```
(plus allowed local pyenv hashlib `blake2b` / `blake2s` warnings)

### GREEN
- Command:
```bash
pytest tests/test_jetblue_scrape.py -q
```
- Output summary:
```text
...                                                                      [100%]
3 passed in 0.04s
```
(plus the same allowed pyenv hashlib warnings)
- Command:
```bash
pytest tests/ -q
```
- Output summary:
```text
241 passed, 8 skipped in 0.52s
```
- Command:
```bash
ruff check .
```
- Output:
```text
All checks passed!
```

## Files changed
- `.github/workflows/jetblue-scrape.yml`
- `tests/test_jetblue_scrape.py`
- `README.md`
- `.superpowers/sdd/task-1-report.md` (this report)

## Self-review findings
- Kept modifications scoped to the requested three project files plus the required report.
- Preserved the existing matrix, cron, shard, and max-leg env settings while changing only the probe horizon.
- Formatting in README remains consistent with existing style and table width.

## Issues / concerns
- Known local environment warning from `hashlib` (`blake2b`/`blake2s` unsupported) appears during pytest runs.
  It does not fail tests and was already present/in-scope per repo guidance.
- No other blocking issues identified.

## Follow-up wording fix (temporary one-route one-date wording sync)

- Updated `tests/test_jetblue_scrape.py::test_jetblue_workflow_shard_matrix_is_consistent` wording to explicitly state the scheduled JetBlue probe is one-shard, one-route, one-date while HTTP 406 remains blocked, without changing assertion semantics.
- Updated README sharding paragraph near the bottom to remove the stale “Alaska and JetBlue 5” wording and clarify: Alaska 5 shards, JetBlue temporary one-route/one-date probe (1), Turkish 3, Etihad 2.

### Exact verification run

- `pytest tests/test_jetblue_scrape.py -q`
  - Result: **PASS** (3 passed) with allowed local pyenv `hashlib` `blake2b`/`blake2s` warnings.
- `pytest tests/ -q`
  - Result: **PASS** (241 passed, 8 skipped) with allowed local pyenv `hashlib` `blake2b`/`blake2s` warnings.
- `ruff check .`
  - Result: **PASS**
