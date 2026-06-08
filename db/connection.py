"""
MotherDuck connection — thread-local, one connection per thread.

MotherDuck is serverless cloud DuckDB. The standard `duckdb` package connects
to it via the `md:` connection string prefix. The MOTHERDUCK_TOKEN env var is
automatically picked up by the duckdb package — no explicit auth call needed.

Thread-local storage is required because the API runs blocking scrapes via
asyncio.to_thread() in a worker thread while async DB reads run on the event
loop thread simultaneously. DuckDB connection objects are not thread-safe.

Each thread gets its own independent MotherDuck connection; the server-side
handles concurrent access across connections correctly.
"""

import logging
import threading

import duckdb

logger = logging.getLogger(__name__)

_local = threading.local()


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return this thread's MotherDuck connection, opening it lazily if needed."""
    if not hasattr(_local, "conn") or _local.conn is None:
        logger.info("Opening MotherDuck connection on thread '%s'", threading.current_thread().name)
        conn = duckdb.connect("md:")
        conn.execute("SET TimeZone='UTC'")
        conn.execute("CREATE DATABASE IF NOT EXISTS point_pilot")
        conn.execute("USE point_pilot")
        _local.conn = conn
        logger.info("MotherDuck connection established — using point_pilot")
    return _local.conn


def close_connection() -> None:
    """Close this thread's MotherDuck connection."""
    if hasattr(_local, "conn") and _local.conn is not None:
        _local.conn.close()
        _local.conn = None
        logger.info("MotherDuck connection closed")
