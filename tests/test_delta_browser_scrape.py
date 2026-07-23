from datetime import date

import yaml

from browser_scrape_common import dense_sparse_dates
from delta_browser_scrape import _build_plan, _parse_dates_csv

_WF = ".github/workflows/delta-browser-scrape.yml"


class _StubScraper:
    """Stand-in for DeltaScraper carrying the dense/sparse knobs _run_cron reads off it."""

    dense_days = 14
    sparse_step = 4


def test_parse_dates_csv_valid():
    assert _parse_dates_csv("2026-06-20,2026-06-21") == [date(2026, 6, 20), date(2026, 6, 21)]


def test_delta_workflow_shard_matrix_is_consistent():
    with open(_WF) as f:
        wf = yaml.safe_load(f)
    job = wf["jobs"]["scrape"]
    shards = job["strategy"]["matrix"]["shard"]
    env = job["steps"][-1]["env"]
    n = int(env["DELTA_SHARDS"])
    assert shards == list(range(n)), f"matrix {shards} must be range(DELTA_SHARDS={n})"
    assert n == 1, "scheduled Delta is a single low-cost recovery probe"
    assert env["DELTA_SHARD_INDEX"] == "${{ matrix.shard }}"
    assert env["DELTA_MAX_LEGS_PER_SHARD"] == "1"
    assert env["DELTA_SCRAPE_DAYS"] == "1"
    assert env["CRON_TIME_BUDGET_S"] == "7200"


def test_delta_workflow_runs_once_weekly_and_keeps_manual_dispatch():
    with open(_WF) as f:
        wf = yaml.safe_load(f)
    schedule = wf[True]["schedule"]
    crons = [s["cron"] for s in schedule]
    assert crons == ["0 8 * * 0"]
    assert "workflow_dispatch" in wf[True]


def test_parse_dates_csv_drops_invalid_and_blanks():
    assert _parse_dates_csv("2026-06-20, ,nonsense,2026-06-22") == [
        date(2026, 6, 20),
        date(2026, 6, 22),
    ]


def test_parse_dates_csv_empty():
    assert _parse_dates_csv("") == []


def test_build_plan_single_route_with_dates():
    pairs, dates = _build_plan("atl", "lax", "2026-06-20,2026-06-21", 5, date(2026, 6, 8))
    # requested direction only (no reverse), exactly the supplied dates
    assert pairs == [("ATL", "LAX")]
    assert dates == [date(2026, 6, 20), date(2026, 6, 21)]


def test_build_plan_single_route_no_dates_falls_back_to_window():
    pairs, dates = _build_plan("ATL", "LAX", "", 3, date(2026, 6, 8))
    assert pairs == [("ATL", "LAX")]
    assert dates == [date(2026, 6, 8), date(2026, 6, 9), date(2026, 6, 10)]


def test_build_plan_single_route_only_shard0_works():
    # On-demand single-route dispatch spawns both matrix shards, but only shard 0 scrapes;
    # other shards no-op so the route isn't scraped twice.
    p0, d0 = _build_plan("ATL", "LAX", "", 5, date(2026, 6, 8), shard_index=0, shards=2)
    p1, d1 = _build_plan("ATL", "LAX", "", 5, date(2026, 6, 8), shard_index=1, shards=2)
    assert p0 == [("ATL", "LAX")] and d0
    assert p1 == [] and d1 == []


def test_delta_cron_uses_queue(monkeypatch):
    import delta_browser_scrape as ep

    calls = {}

    def fake_build_queue_plan(airline, **kw):
        calls.update(airline=airline, **kw)
        return (["JOB"], ["DATE"])

    monkeypatch.setattr(ep.common, "build_queue_plan", fake_build_queue_plan)
    monkeypatch.setattr(ep.common, "run_scrape", lambda *a, **k: 0)
    monkeypatch.setattr("scrapers.delta.DeltaScraper", _StubScraper)

    ep._run_cron(shard_index=0, shards=3)
    assert calls["airline"] == "delta"
    assert calls["max_legs"] == ep.MAX_LEGS_PER_SHARD
    assert calls["shard_index"] == 0
    assert calls["shards"] == 3


class _FixedDate:
    """date stand-in whose .today() is pinned; the entrypoint only calls date.today()."""

    def __init__(self, pinned):
        self._pinned = pinned

    def today(self):
        return self._pinned


def test_dense_sparse_recovery_horizon_is_exactly_one_date():
    today = date(2026, 6, 25)
    assert dense_sparse_dates(today, dense_days=14, sparse_step=4, max_day=1) == [today]


def test_delta_cron_uses_exactly_one_recovery_date(monkeypatch):
    """The weekly recovery cron must remain one selected route by one date."""
    import delta_browser_scrape as ep

    captured = {}
    monkeypatch.setattr(
        ep.common, "build_queue_plan", lambda *a, **k: (["JOB"], ["IGNORED_DATE"])
    )
    monkeypatch.setattr(
        ep.common, "run_scrape",
        lambda scraper, pairs, dates, **kw: captured.update(dates=dates) or 0,
    )
    monkeypatch.setattr("scrapers.delta.DeltaScraper", _StubScraper)

    today = date(2026, 6, 25)
    monkeypatch.setattr(ep, "date", _FixedDate(today))
    monkeypatch.setattr(ep, "SCRAPE_DAYS", 1)  # the workflow sets DELTA_SCRAPE_DAYS=1

    ep._run_cron(shard_index=0, shards=1)

    dates = captured["dates"]
    assert dates != ["IGNORED_DATE"]  # regenerated, not the queue's flat every-day list
    assert dates == [today]
