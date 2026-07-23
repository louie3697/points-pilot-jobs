from datetime import date
from types import SimpleNamespace

from turkish_browser_scrape import _build_plan, _parse_dates_csv


def test_parse_dates_csv_valid_and_invalid():
    assert _parse_dates_csv("2026-06-20, ,nonsense,2026-06-22") == [
        date(2026, 6, 20),
        date(2026, 6, 22),
    ]


def test_build_plan_single_route():
    pairs, dates = _build_plan("jfk", "ist", "2026-06-20,2026-06-21", 3, date(2026, 6, 13))
    assert pairs == [("JFK", "IST")]  # requested direction only
    assert dates == [date(2026, 6, 20), date(2026, 6, 21)]


def test_build_plan_single_route_no_dates_falls_back_to_window():
    pairs, dates = _build_plan("JFK", "IST", "", 3, date(2026, 6, 13))
    assert pairs == [("JFK", "IST")]
    assert dates == [date(2026, 6, 13), date(2026, 6, 14), date(2026, 6, 15)]


def test_turkish_cron_uses_queue(monkeypatch):
    import turkish_browser_scrape as ep

    calls = {}

    def fake_build_queue_plan(airline, **kw):
        calls.update(airline=airline, **kw)
        return (["JOB"], ["DATE"])

    monkeypatch.setattr(ep.common, "build_queue_plan", fake_build_queue_plan)
    monkeypatch.setattr(ep.common, "run_scrape", lambda *a, **k: 0)
    monkeypatch.setattr("scrapers.turkish.TurkishScraper", lambda *a, **k: object())

    ep._run_cron(shard_index=0, shards=1)
    assert calls["airline"] == "turkish"
    assert calls["max_legs"] == ep.MAX_LEGS_PER_SHARD
    assert calls["shard_index"] == 0
    assert calls["shards"] == 1


def _capture_cron(monkeypatch, *, route_jobs, source_rows, shard_index):
    import turkish_browser_scrape as ep

    captured = {}
    freshness_calls = []
    monkeypatch.setattr(
        ep.common,
        "build_queue_plan",
        lambda *args, **kwargs: (route_jobs, [date(2026, 7, 24), date(2026, 7, 25)]),
    )
    monkeypatch.setattr(
        ep.common,
        "freshness",
        lambda source, logger: freshness_calls.append(source)
        or {"turkish_rows": source_rows, "turkish_newest_age_h": None},
    )
    monkeypatch.setattr(
        ep.common,
        "run_scrape",
        lambda scraper, pairs, dates, **kwargs: captured.update(
            pairs=pairs, dates=dates, kwargs=kwargs
        )
        or SimpleNamespace(status="healthy"),
    )
    monkeypatch.setattr("scrapers.turkish.TurkishScraper", lambda *args, **kwargs: object())

    ep._run_cron(shard_index=shard_index, shards=3)
    return captured, freshness_calls


def test_turkish_shard_zero_uses_one_unqueued_recovery_probe_when_zero_data(monkeypatch):
    captured, freshness_calls = _capture_cron(
        monkeypatch, route_jobs=[], source_rows=0, shard_index=0
    )

    assert freshness_calls == ["turkish"]
    assert captured["pairs"] == [("JFK", "IST")]
    assert captured["dates"] == [date.today()]
    assert captured["kwargs"]["route_jobs"] is None


def test_turkish_nonzero_shards_do_not_use_zero_data_recovery_probe(monkeypatch):
    captured, freshness_calls = _capture_cron(
        monkeypatch, route_jobs=[], source_rows=0, shard_index=1
    )

    assert freshness_calls == []
    assert captured["pairs"] == []
    assert captured["kwargs"]["route_jobs"] == []


def test_turkish_existing_rows_suppress_zero_data_recovery_probe(monkeypatch):
    captured, freshness_calls = _capture_cron(
        monkeypatch, route_jobs=[], source_rows=1, shard_index=0
    )

    assert freshness_calls == ["turkish"]
    assert captured["pairs"] == []
    assert captured["kwargs"]["route_jobs"] == []


def test_turkish_due_queue_work_suppresses_zero_data_recovery_probe(monkeypatch):
    due_job = SimpleNamespace(origin="EWR", dest="IST")
    captured, freshness_calls = _capture_cron(
        monkeypatch, route_jobs=[due_job], source_rows=0, shard_index=0
    )

    assert freshness_calls == []
    assert captured["pairs"] == []
    assert captured["kwargs"]["route_jobs"] == [due_job]
