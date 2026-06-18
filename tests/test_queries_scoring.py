"""jobs db/queries gain the scoring columns + adaptive write path (vendored from scraper)."""

from datetime import datetime, timezone

import duckdb
import pytest

from db import queries as db


@pytest.fixture(autouse=True)
def conn():
    import db.connection as db_conn

    c = duckdb.connect(":memory:")
    c.execute("SET TimeZone='UTC'")
    db_conn._local.conn = c
    from db import schema

    schema.migrate()
    yield c
    db_conn._local.conn = None
    c.close()


def test_get_due_routes_has_scoring_columns():
    db.upsert_route("ATL", "LAX", "MED", airline="delta")
    db.get_connection().execute(
        "UPDATE routes_queue SET next_scrape_at_utc = now() - INTERVAL '1 hour'"
    )
    rows = db.get_due_routes(limit=10, airline="delta")
    assert rows
    for k in ("decayed_demand", "last_search_at", "change_rate", "interval_h", "last_cheapest"):
        assert k in rows[0]


def test_record_scrape_outcome_persists():
    nxt = datetime(2026, 6, 19, tzinfo=timezone.utc)
    db.upsert_route("ATL", "LAX", "MED", airline="delta")
    db.record_scrape_outcome(
        "ATL",
        "LAX",
        "delta",
        interval_h=12.0,
        change_rate=0.65,
        last_cheapest='{"economy": 9000}',
        next_scrape_at=nxt,
    )
    row = db.get_connection().execute(
        "SELECT interval_h, change_rate, last_cheapest FROM routes_queue "
        "WHERE origin='ATL' AND dest='LAX'"
    ).fetchone()
    assert row == (12.0, 0.65, '{"economy": 9000}')
