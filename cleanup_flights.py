#!/usr/bin/env python3
"""
cleanup_flights — delete stale rows from the MotherDuck `flights` table.

Runs daily on a GitHub Actions cron. Deletes every flight whose departure
`date` is older than yesterday (UTC) — i.e. it keeps yesterday plus everything
forward, and drops everything before yesterday. The connection is pinned to UTC
so `current_date` resolves to the UTC calendar date regardless of where the
runner happens to live.

This mirrors the scraper's own `expire_stale_flights()` cleanup: `expires_at` is
a scrape-freshness TTL, NOT a signal that the flight is gone, so cleanup is
anchored to the actual flight `date`.

Requires MOTHERDUCK_TOKEN in the environment — the duckdb package picks it up
automatically when opening an `md:` connection.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import duckdb

logger = logging.getLogger("cleanup_flights")

# Strictly older than yesterday (UTC). `current_date - INTERVAL '1 day'` is
# yesterday, so `date < yesterday` keeps yesterday + today + future and deletes
# everything before. Identical to the scraper's expire_stale_flights() predicate.
STALE_PREDICATE = "date < current_date - INTERVAL '1 day'"


def connect() -> duckdb.DuckDBPyConnection:
    """Open a UTC-pinned MotherDuck connection to the point_pilot database."""
    if not os.environ.get("MOTHERDUCK_TOKEN"):
        logger.error("MOTHERDUCK_TOKEN is not set — cannot connect to MotherDuck.")
        sys.exit(1)
    conn = duckdb.connect("md:point_pilot")
    conn.execute("SET TimeZone='UTC'")
    return conn


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many rows would be deleted, without deleting anything.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    conn = connect()

    # Resolve the cutoff once so logs name the exact UTC boundary being applied.
    cutoff = conn.execute("SELECT (current_date - INTERVAL '1 day')::DATE").fetchone()[0]

    if args.dry_run:
        stale = conn.execute(
            f"SELECT count(*) FROM flights WHERE {STALE_PREDICATE}"
        ).fetchone()[0]
        logger.info(
            "[dry-run] %d flight row(s) with date < %s (UTC) would be deleted.",
            stale,
            cutoff,
        )
        return 0

    # DuckDB's DELETE returns a single-row result holding the number of rows removed.
    deleted = conn.execute(f"DELETE FROM flights WHERE {STALE_PREDICATE}").fetchone()[0]
    logger.info("Deleted %d flight row(s) with date < %s (UTC).", deleted, cutoff)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
