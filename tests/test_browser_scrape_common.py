"""Queue-mode (`build_queue_plan` + adaptive marking in `run_scrape`) for the shared cron runner.

The legacy on-demand path (`run_scrape(..., route_jobs=None)`) is exercised by the per-airline
`_build_plan`/`_parse_dates_csv` tests; these focus on the new queue-aware path.
"""

import logging
from datetime import date

import duckdb
import pytest

import browser_scrape_common as common
from config.settings import PriorityTier
from db import queries as db


@pytest.fixture(autouse=True)
def conn(monkeypatch):
    import db.connection as db_conn

    c = duckdb.connect(":memory:")
    c.execute("SET TimeZone='UTC'")
    db_conn._local.conn = c
    # run_scrape's finally: close_connection() would tear down this in-memory DB (destroying the
    # seeded rows we assert on afterwards) and force a real md: reconnect. Keep the shared
    # connection alive across the run so the test can read the adaptive-mark result.
    monkeypatch.setattr(db_conn, "close_connection", lambda: None)
    from db import schema

    schema.migrate()
    yield c
    db_conn._local.conn = None
    c.close()


def _seed_due(n, airline="delta"):
    for i in range(n):
        db.upsert_route(f"O{i:02d}", f"D{i:02d}", PriorityTier.MED, airline=airline)
    db.get_connection().execute(
        "UPDATE routes_queue SET next_scrape_at_utc = now() - INTERVAL '1 hour'"
    )


def test_build_queue_plan_strides_disjoint_and_caps():
    _seed_due(12)
    today = date(2026, 6, 18)
    jobs0, dates = common.build_queue_plan(
        "delta", shard_index=0, shards=3, max_legs=2, scrape_days=3, today=today
    )
    jobs1, _ = common.build_queue_plan(
        "delta", shard_index=1, shards=3, max_legs=2, scrape_days=3, today=today
    )
    assert len(jobs0) == 2 and len(jobs1) == 2  # per-shard cap
    s0 = {(j.origin, j.dest) for j in jobs0}
    s1 = {(j.origin, j.dest) for j in jobs1}
    assert s0.isdisjoint(s1)  # disjoint strides
    assert len(dates) == 3


def test_run_scrape_queue_mode_marks_adaptively():
    _seed_due(1)
    today = date(2026, 6, 18)
    route_jobs, dates = common.build_queue_plan(
        "delta", shard_index=0, shards=1, max_legs=5, scrape_days=1, today=today
    )

    class _Scraper:
        source = "delta"

        def scrape(self, o, d, travel):
            return []  # zero rows: still a successful (non-blocked) scrape -> route marked

        def close(self):
            pass

    common.run_scrape(
        _Scraper(),
        [],
        dates,
        source="delta",
        service="point-pilot-delta",
        airline="delta",
        heartbeat_url="",
        logger=logging.getLogger("t"),
        route_jobs=route_jobs,
    )
    row = db.get_connection().execute(
        "SELECT interval_h FROM routes_queue WHERE airline='delta' AND interval_h IS NOT NULL"
    ).fetchone()
    assert row is not None  # the scraped route was marked adaptively


def test_run_scrape_queue_mode_blocked_route_stays_due(conn):
    """The critical safety invariant: a WAF-blocked route is NEVER marked (stays due)."""
    from scrapers.base import ScraperBlockedError

    _seed_due(1)
    today = date(2026, 6, 18)
    route_jobs, dates = common.build_queue_plan(
        "delta", shard_index=0, shards=1, max_legs=5, scrape_days=1, today=today
    )

    class _Blocking:
        source = "delta"

        def scrape(self, o, d, travel):
            raise ScraperBlockedError("WAF")

        def close(self):
            pass

    common.run_scrape(
        _Blocking(),
        [],
        dates,
        source="delta",
        service="point-pilot-delta",
        airline="delta",
        heartbeat_url="",
        logger=logging.getLogger("t"),
        route_jobs=route_jobs,
    )
    # No interval_h was written, and last_scraped is still NULL -> route remains due.
    marked = conn.execute(
        "SELECT count(*) FROM routes_queue WHERE airline='delta' AND interval_h IS NOT NULL"
    ).fetchone()[0]
    assert marked == 0
