from datetime import date

from southwest_browser_scrape import _build_plan, _parse_dates_csv


class _StubScraper:
    """Stand-in for SouthwestScraper carrying the dense/sparse knobs _run_cron reads off it."""

    dense_days = 7
    sparse_step = 6


def test_parse_dates_csv_valid_and_invalid():
    assert _parse_dates_csv("2026-06-20, ,nonsense,2026-06-22") == [
        date(2026, 6, 20),
        date(2026, 6, 22),
    ]


def test_build_plan_single_route():
    pairs, dates = _build_plan("sea", "lax", "2026-06-20,2026-06-21", 5, date(2026, 6, 13))
    assert pairs == [("SEA", "LAX")]  # requested direction only
    assert dates == [date(2026, 6, 20), date(2026, 6, 21)]


def test_build_plan_single_route_no_dates_falls_back_to_window():
    pairs, dates = _build_plan("SEA", "LAX", "", 3, date(2026, 6, 13))
    assert pairs == [("SEA", "LAX")]
    assert dates == [date(2026, 6, 13), date(2026, 6, 14), date(2026, 6, 15)]


def test_southwest_cron_uses_queue(monkeypatch):
    import southwest_browser_scrape as ep

    calls = {}

    def fake_build_queue_plan(airline, **kw):
        calls.update(airline=airline, **kw)
        return (["JOB"], ["DATE"])

    monkeypatch.setattr(ep.common, "build_queue_plan", fake_build_queue_plan)
    monkeypatch.setattr(ep.common, "run_scrape", lambda *a, **k: 0)
    monkeypatch.setattr("scrapers.southwest.SouthwestScraper", _StubScraper)

    ep._run_cron(shard_index=1, shards=2)
    assert calls["airline"] == "southwest"
    assert calls["max_legs"] == ep.MAX_LEGS_PER_SHARD
    assert calls["shard_index"] == 1
    assert calls["shards"] == 2


class _FixedDate:
    """date stand-in whose .today() is pinned; the entrypoint only calls date.today()."""

    def __init__(self, pinned):
        self._pinned = pinned

    def today(self):
        return self._pinned


def test_southwest_cron_uses_dense_sparse_horizon(monkeypatch):
    """The cron path regenerates dates via dense_sparse over the 90d window (NOT
    build_queue_plan's every-day list): a lean count (leaner than Delta, ~<=20) spanning ~90
    days, dense near-term — respecting Southwest's F5/Shape ceiling + 150-min job timeout."""
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
    monkeypatch.setattr(ep, "SCRAPE_DAYS", 90)  # the workflow sets SOUTHWEST_SCRAPE_DAYS=90

    ep._run_cron(shard_index=0, shards=1)

    dates = captured["dates"]
    offsets = sorted((d - today).days for d in dates)
    assert dates != ["IGNORED_DATE"]  # regenerated, not the queue's flat every-day list
    assert offsets[:3] == [0, 1, 2]  # dense near-term, every day
    assert 80 <= offsets[-1] < 90  # reaches the ~90d horizon (exclusive upper bound)
    assert len(dates) <= 20  # lean per-session budget (Southwest's F5/Shape + timeout)
