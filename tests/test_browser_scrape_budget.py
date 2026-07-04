"""Hermetic tests for the wall-clock time budget in ``run_scrape`` (no DB).

A long scheduled cron used to run until its whole shard slice drained, which on AS/B6
overran the GitHub-Actions 60-minute job cap and got hard-cancelled mid-run — losing the
``scrape_run`` metric + heartbeat and leaving in-flight routes unmarked. ``run_scrape`` now
stops cleanly between routes once ``time_budget_s`` is reached, ships its metric, and exits;
the routes it didn't reach simply stay due for the next run.

These drive the on-demand path (``route_jobs=None``) so no ``pp`` schema is needed; the DB/obs
boundaries are stubbed so the budget *logic* is what's under test.
"""

from __future__ import annotations

import logging
from datetime import date
from types import SimpleNamespace

import browser_scrape_common as common
from config.settings import SCRAPER_BLOCK_COOLDOWN_MIN


class _FakeScraper:
    source = "jetblue"

    def __init__(self):
        self.calls = 0

    def scrape(self, origin, dest, travel):
        self.calls += 1
        return []  # zero rows: a successful (non-blocked) scrape

    def close(self):
        pass


def _stub_io(monkeypatch):
    """Stub the DB/obs side effects so only the budget loop logic runs. Returns the captured
    ``ship_metric`` payloads."""
    metrics: list[dict] = []
    monkeypatch.setattr("pipeline.obs.ship_metric", lambda payload: metrics.append(payload))
    monkeypatch.setattr(common, "freshness", lambda *a, **k: {})
    monkeypatch.setattr("pp_db.autocommit.close_connection", lambda: None)
    return metrics


def test_run_scrape_stops_before_scraping_when_budget_exhausted(monkeypatch):
    metrics = _stub_io(monkeypatch)
    scraper = _FakeScraper()

    total = common.run_scrape(
        scraper,
        [("SEA", "JFK"), ("LAX", "BOS")],
        [date(2026, 7, 1)],
        source="jetblue",
        service="point-pilot-jetblue",
        airline="B6",
        heartbeat_url="",
        logger=logging.getLogger("t"),
        time_budget_s=0,  # already over budget -> stop before the first route
    )

    assert scraper.calls == 0  # no route scraped
    assert total == 0
    assert metrics, "scrape_run metric must still ship on a budget stop"
    assert metrics[0]["routes_scraped"] == 0
    assert metrics[0]["stopped_early"] is True


def test_run_scrape_completes_all_routes_within_generous_budget(monkeypatch):
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
        time_budget_s=3600,  # plenty of headroom -> no early stop
    )

    assert scraper.calls == 2  # both routes scraped
    assert metrics[0]["routes_scraped"] == 2
    assert metrics[0]["stopped_early"] is False


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


def test_run_scrape_queue_mode_blocked_route_sets_backoff_and_metric_fields(monkeypatch):
    import pipeline.queue_manager as queue_manager
    from scrapers.base import ScraperBlockedError

    metrics = _stub_io(monkeypatch)
    blocked_calls: list[tuple[str, str, str, int]] = []

    class _BlockingScraper:
        source = "jetblue"

        def scrape(self, origin, dest, travel):
            raise ScraperBlockedError("WAF")

        def close(self):
            pass

    class _FakeQM:
        def __init__(self, scraper=None):
            pass

        def mark_blocked(self, job, now, cooldown_min):
            blocked_calls.append((job.origin, job.dest, job.airline, cooldown_min))

    monkeypatch.setattr(queue_manager, "QueueManager", _FakeQM)
    route_jobs = [
        SimpleNamespace(
            origin="SEA",
            dest="JFK",
            airline="jetblue",
            tier="MED",
            queue_due_count=4,
        )
    ]

    common.run_scrape(
        _BlockingScraper(),
        [],
        [date(2026, 7, 1)],
        source="jetblue",
        service="point-pilot-jetblue",
        airline="jetblue",
        heartbeat_url="",
        logger=logging.getLogger("t"),
        route_jobs=route_jobs,
        time_budget_s=3600,
    )

    assert blocked_calls == [("SEA", "JFK", "jetblue", SCRAPER_BLOCK_COOLDOWN_MIN)]
    assert metrics
    assert metrics[0]["blocked"] is True
    assert metrics[0]["blocked_route"] == "SEA-JFK"
    assert metrics[0]["blocked_airline"] == "jetblue"
    assert metrics[0]["blocked_backoff_min"] == SCRAPER_BLOCK_COOLDOWN_MIN
    assert metrics[0]["queue_selected_routes"] == 1
    assert metrics[0]["queue_left_due_estimate"] == 3
    assert metrics[0]["queue_fill_ratio"] == 0.25
    assert metrics[0]["routes_zero"] == 0
