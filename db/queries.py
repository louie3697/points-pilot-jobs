"""
All SQL query functions for point_pilot.

No raw SQL strings anywhere else in the codebase — everything goes through here.
Functions return plain Python dicts/lists so callers never touch duckdb internals.
"""

import logging
from datetime import date, datetime, timezone
from typing import Any

from db.connection import get_connection
from scrapers.base import CashFareRecord, FlightRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Flights
# ---------------------------------------------------------------------------

_UPSERT_FLIGHT = """
INSERT INTO flights (
    origin, destination, date, airline, program, source,
    points_cost, cash_cost, stops, cabin_class,
    available_seats, raw_flight_number, partner_airline,
    scraped_at_utc, expires_at_utc,
    departure_time_local, arrival_time_local, duration_minutes, aircraft_type,
    is_saver, fare_class, layover_airports, layover_duration_minutes,
    next_day_arrival, mixed_cabin
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (origin, destination, date, airline, cabin_class, raw_flight_number)
DO UPDATE SET
    source                   = excluded.source,
    points_cost              = excluded.points_cost,
    cash_cost                = excluded.cash_cost,
    stops                    = excluded.stops,
    available_seats          = excluded.available_seats,
    partner_airline          = excluded.partner_airline,
    scraped_at_utc           = excluded.scraped_at_utc,
    expires_at_utc           = excluded.expires_at_utc,
    departure_time_local     = excluded.departure_time_local,
    arrival_time_local       = excluded.arrival_time_local,
    duration_minutes         = excluded.duration_minutes,
    aircraft_type            = excluded.aircraft_type,
    is_saver                 = excluded.is_saver,
    fare_class               = excluded.fare_class,
    layover_airports         = excluded.layover_airports,
    layover_duration_minutes = excluded.layover_duration_minutes,
    next_day_arrival         = excluded.next_day_arrival,
    mixed_cabin              = excluded.mixed_cabin
"""


def upsert_flights(records: list[FlightRecord]) -> int:
    """
    Insert or update a batch of FlightRecord objects.
    Returns the number of records processed.
    """
    if not records:
        return 0

    conn = get_connection()
    rows = [
        (
            r.origin,
            r.destination,
            r.date,
            r.airline,
            r.program,
            r.source,
            r.points_cost,
            r.cash_cost,
            r.stops,
            r.cabin_class,
            r.available_seats,
            r.raw_flight_number or "UNKNOWN",  # sentinel — UNIQUE constraint needs non-NULL
            r.partner_airline,
            r.scraped_at_utc,
            r.expires_at_utc,
            r.departure_time_local,
            r.arrival_time_local,
            r.duration_minutes,
            r.aircraft_type,
            r.is_saver,
            r.fare_class,
            r.layover_airports,
            r.layover_duration_minutes,
            r.next_day_arrival,
            r.mixed_cabin,
        )
        for r in records
    ]

    conn.executemany(_UPSERT_FLIGHT, rows)
    logger.debug("Upserted %d flight records", len(rows))
    return len(rows)


def get_flights(
    origin: str,
    destination: str,
    date_from: date,
    date_to: date,
    cabin_class: str | None = None,
    max_points: int | None = None,
    airline: str | None = None,
    fresh_only: bool = True,
) -> list[dict[str, Any]]:
    """
    Query available flights for a route + date range.

    Args:
        fresh_only: If True, only return rows whose flight date is today or
                    later. expires_at is *not* used to filter — it represents
                    how stale our cached scrape is, not whether the flight is
                    still bookable. Callers display scraped_at on each card
                    so users can judge for themselves.
    """
    conn = get_connection()

    filters = ["f.origin = ?", "f.destination = ?", "f.date BETWEEN ? AND ?"]
    params: list[Any] = [origin, destination, date_from, date_to]

    if cabin_class:
        filters.append("f.cabin_class = ?")
        params.append(cabin_class)
    if max_points:
        filters.append("f.points_cost <= ?")
        params.append(max_points)
    if airline:
        # `airline` is the program carrier each scraper stamps (AS/DL/AA/B6),
        # so this filters to one airline's award space, e.g. "on JetBlue" → B6.
        filters.append("f.airline = ?")
        params.append(airline)
    if fresh_only:
        filters.append("f.date >= current_date")

    where = " AND ".join(filters)
    sql = f"""
        SELECT
            f.id, f.origin, f.destination, f.date, f.airline, f.program, f.source,
            f.points_cost, f.cash_cost, f.stops, f.cabin_class,
            f.available_seats, f.raw_flight_number, f.partner_airline,
            f.scraped_at_utc AS scraped_at, f.expires_at_utc AS expires_at,
            f.departure_time_local AS departure_time, f.arrival_time_local AS arrival_time,
            f.duration_minutes, f.aircraft_type,
            f.is_saver, f.fare_class, f.layover_airports, f.layover_duration_minutes,
            f.next_day_arrival, f.mixed_cabin,
            c.cash_price,
            CASE WHEN c.cash_price IS NOT NULL AND f.points_cost > 0
                 THEN round(c.cash_price / f.points_cost * 100, 2) END AS cpp
        FROM flights f
        LEFT JOIN cash_fares c
               ON c.origin = f.origin AND c.destination = f.destination AND c.date = f.date
              AND c.airline = f.airline AND c.cabin_class = f.cabin_class
              AND c.flight_number = f.raw_flight_number
              AND c.expires_at_utc > now()
        WHERE {where}
        ORDER BY f.date ASC, f.points_cost ASC
    """

    rows = conn.execute(sql, params).fetchall()
    columns = [
        "id",
        "origin",
        "destination",
        "date",
        "airline",
        "program",
        "source",
        "points_cost",
        "cash_cost",
        "stops",
        "cabin_class",
        "available_seats",
        "raw_flight_number",
        "partner_airline",
        "scraped_at",
        "expires_at",
        "departure_time",
        "arrival_time",
        "duration_minutes",
        "aircraft_type",
        "is_saver",
        "fare_class",
        "layover_airports",
        "layover_duration_minutes",
        "next_day_arrival",
        "mixed_cabin",
        "cash_price",
        "cpp",
    ]
    return [dict(zip(columns, row, strict=False)) for row in rows]


def get_fresh_scrape_dates(origin: str, destination: str, source: str | None = None) -> set[date]:
    """
    Return the set of flight dates that already have at least one row with a
    non-expired scrape (expires_at > now()). Used by handle_user_search to
    decide which dates an on-demand search should re-scrape — we skip the
    ones we just refreshed and only hit the airline for what's missing.

    `source` (scraper slug, e.g. "delta") scopes freshness to one scraper so a
    different airline's coverage of the same route doesn't suppress this one's scrape.
    """
    conn = get_connection()
    sql = (
        "SELECT DISTINCT date FROM flights "
        "WHERE origin = ? AND destination = ? AND expires_at_utc > now()"
    )
    params: list[Any] = [origin, destination]
    if source:
        sql += " AND source = ?"
        params.append(source)
    rows = conn.execute(sql, params).fetchall()
    return {row[0] for row in rows}


def upsert_cash_fare(
    origin: str,
    destination: str,
    date: date,
    airline: str,
    cabin_class: str,
    flight_number: str,
    cash_price: float,
    scraped_at_utc: datetime,
    expires_at_utc: datetime,
    currency: str = "USD",
    source: str = "google_flights",
) -> None:
    """Insert or update one cash fare (per-flight grain; shares flights' natural key).

    Only for nonstop flights with a known flight number. Multi-leg awards carry the
    "UNKNOWN" sentinel in flights.raw_flight_number and intentionally have no cash_fares
    counterpart, so get_flights returns NULL cpp for them.
    """
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO cash_fares
            (origin, destination, date, airline, cabin_class, flight_number,
             cash_price, currency, source, scraped_at_utc, expires_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (origin, destination, date, airline, cabin_class, flight_number)
        DO UPDATE SET
            cash_price     = excluded.cash_price,
            currency       = excluded.currency,
            source         = excluded.source,
            scraped_at_utc = excluded.scraped_at_utc,
            expires_at_utc = excluded.expires_at_utc
        """,
        [
            origin,
            destination,
            date,
            airline,
            cabin_class,
            flight_number,
            cash_price,
            currency,
            source,
            scraped_at_utc,
            expires_at_utc,
        ],
    )


_UPSERT_CASH_FARE_BATCH = """
INSERT INTO cash_fares
    (origin, destination, date, airline, cabin_class, flight_number,
     cash_price, currency, source, scraped_at_utc, expires_at_utc)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (origin, destination, date, airline, cabin_class, flight_number)
DO UPDATE SET
    cash_price     = excluded.cash_price,
    currency       = excluded.currency,
    source         = excluded.source,
    scraped_at_utc = excluded.scraped_at_utc,
    expires_at_utc = excluded.expires_at_utc
"""


def upsert_cash_fares(records: list[CashFareRecord]) -> int:
    """Batch insert/update cash fares on the natural key. Returns rows processed.

    Scraper-only (the Alaska cash job writes these); not used by the api. Mirrors the
    single-row upsert_cash_fare, which stays for ad-hoc/test use.
    """
    if not records:
        return 0
    conn = get_connection()
    rows = [
        (
            r.origin,
            r.destination,
            r.date,
            r.airline,
            r.cabin_class,
            r.flight_number,
            r.cash_price,
            r.currency,
            r.source,
            r.scraped_at_utc,
            r.expires_at_utc,
        )
        for r in records
    ]
    conn.executemany(_UPSERT_CASH_FARE_BATCH, rows)
    logger.debug("Upserted %d cash fares", len(rows))
    return len(rows)


# ---------------------------------------------------------------------------
# Routes Queue
# ---------------------------------------------------------------------------


def upsert_route(origin: str, dest: str, tier: str, airline: str = "alaska") -> None:
    """
    Add a route to the queue if it doesn't exist (per airline).
    Idempotent — existing rows are not modified.
    """
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO routes_queue (origin, dest, airline, priority_tier)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (origin, dest, airline) DO NOTHING
        """,
        [origin, dest, airline, tier],
    )


def get_due_routes(limit: int = 50, airline: str | None = None) -> list[dict[str, Any]]:
    """
    Return routes whose next_scrape_at has passed, ordered by priority + staleness.

    Priority order: HIGH → MED → LOW, then by next_scrape_at ASC (most overdue first).
    `airline` filters to one scraper's queue (None = all airlines).
    """
    conn = get_connection()
    filters = ["next_scrape_at_utc <= now()"]
    params: list[Any] = []
    if airline:
        filters.append("airline = ?")
        params.append(airline)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
            origin, dest, airline, priority_tier, search_count,
            last_scraped_at_utc AS last_scraped_at, next_scrape_at_utc AS next_scrape_at,
            decayed_demand, last_search_at_utc AS last_search_at, change_rate,
            interval_h, last_cheapest
        FROM routes_queue
        WHERE {" AND ".join(filters)}
        ORDER BY
            CASE priority_tier WHEN 'HIGH' THEN 1 WHEN 'MED' THEN 2 ELSE 3 END,
            next_scrape_at_utc ASC
        LIMIT ?
        """,
        params,
    ).fetchall()

    columns = [
        "origin",
        "dest",
        "airline",
        "priority_tier",
        "search_count",
        "last_scraped_at",
        "next_scrape_at",
        "decayed_demand",
        "last_search_at",
        "change_rate",
        "interval_h",
        "last_cheapest",
    ]
    return [dict(zip(columns, row, strict=False)) for row in rows]


def bump_decayed_demand(
    origin: str, dest: str, airline: str, now: "datetime", half_life_days: float
) -> float:
    """Decay the route's stored demand to ``now`` and add 1 for a new search. Creates the row
    (LOW) if absent. Returns the new decayed_demand. Read-modify-write under the single writer."""
    from pipeline import scoring

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO routes_queue (origin, dest, airline, priority_tier)
        VALUES (?, ?, ?, 'LOW')
        ON CONFLICT (origin, dest, airline) DO NOTHING
        """,
        [origin, dest, airline],
    )
    row = conn.execute(
        "SELECT decayed_demand, last_search_at_utc FROM routes_queue "
        "WHERE origin=? AND dest=? AND airline=?",
        [origin, dest, airline],
    ).fetchone()
    stored = row[0] if row else 0.0
    last = row[1] if row else None
    # DuckDB returns last_search_at_utc as a NAIVE TIMESTAMP; coerce to aware UTC so it's
    # subtractable from the aware `now` in scoring.decay_demand (mirrors checkout_budget /
    # queue_manager._as_utc). Without this the SECOND search of a route raises TypeError.
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    new_val = scoring.bump_demand(stored, last, now, half_life_days)
    conn.execute(
        "UPDATE routes_queue SET decayed_demand = ?, last_search_at_utc = ? "
        "WHERE origin=? AND dest=? AND airline=?",
        [new_val, now, origin, dest, airline],
    )
    return new_val


def record_scrape_outcome(
    origin: str,
    dest: str,
    airline: str,
    *,
    interval_h: float,
    change_rate: float,
    last_cheapest: str,
    next_scrape_at: "datetime",
) -> None:
    """Persist a route's adaptive-scrape outcome: stamps last_scraped now, sets next_scrape_at
    to the adaptive interval, and saves change_rate / interval_h / last_cheapest (JSON string).
    Assumes the route row already exists — this bare UPDATE no-ops on a missing route (unlike
    bump_decayed_demand, which inserts the row first)."""
    conn = get_connection()
    conn.execute(
        """
        UPDATE routes_queue
        SET last_scraped_at_utc = now(),
            next_scrape_at_utc  = ?,
            interval_h          = ?,
            change_rate         = ?,
            last_cheapest       = ?
        WHERE origin = ? AND dest = ? AND airline = ?
        """,
        [next_scrape_at, interval_h, change_rate, last_cheapest, origin, dest, airline],
    )


def mark_route_scraped(
    origin: str, dest: str, tier: str, ttl_hours: int, airline: str = "alaska"
) -> None:
    """
    Update a route after a successful scrape (per airline).
    Sets last_scraped_at = now(), next_scrape_at = now() + ttl_hours.
    """
    conn = get_connection()
    conn.execute(
        """
        UPDATE routes_queue
        SET
            last_scraped_at_utc = now(),
            next_scrape_at_utc  = now() + (? * INTERVAL '1 hour')
        WHERE origin = ? AND dest = ? AND airline = ?
        """,
        [ttl_hours, origin, dest, airline],
    )


def reset_all_route_schedules() -> int:
    """
    Mark every route as due-for-scrape RIGHT NOW.

    Called on scraper startup so the first scheduler tick always picks every
    route up — otherwise a freshly-deployed scraper sits idle for hours while
    the prior deploy's next_scrape_at timestamps elapse, and users see stale
    data the whole time.
    """
    conn = get_connection()
    conn.execute("UPDATE routes_queue SET next_scrape_at_utc = now()")
    n = conn.execute("SELECT count(*) FROM routes_queue").fetchone()[0]
    return n


def increment_search_count(origin: str, dest: str, airline: str = "alaska") -> int:
    """
    Increment search_count for a route (per airline). Returns the new count.
    If the route doesn't exist yet, creates it as LOW tier.
    """
    conn = get_connection()
    # Ensure the row exists (idempotent)
    conn.execute(
        """
        INSERT INTO routes_queue (origin, dest, airline, priority_tier)
        VALUES (?, ?, ?, 'LOW')
        ON CONFLICT (origin, dest, airline) DO NOTHING
        """,
        [origin, dest, airline],
    )
    conn.execute(
        "UPDATE routes_queue SET search_count = search_count + 1 "
        "WHERE origin = ? AND dest = ? AND airline = ?",
        [origin, dest, airline],
    )
    row = conn.execute(
        "SELECT search_count FROM routes_queue WHERE origin = ? AND dest = ? AND airline = ?",
        [origin, dest, airline],
    ).fetchone()
    return row[0] if row else 0


def set_route_tier(origin: str, dest: str, new_tier: str, airline: str = "alaska") -> None:
    """Update the priority tier for a route (per airline)."""
    conn = get_connection()
    conn.execute(
        "UPDATE routes_queue SET priority_tier = ? WHERE origin = ? AND dest = ? AND airline = ?",
        [new_tier, origin, dest, airline],
    )


def get_route(origin: str, dest: str, airline: str = "alaska") -> dict[str, Any] | None:
    """Fetch a single route queue entry (per airline), or None if not found."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT origin, dest, airline, priority_tier, search_count,
               last_scraped_at_utc AS last_scraped_at, next_scrape_at_utc AS next_scrape_at,
               decayed_demand, last_search_at_utc AS last_search_at, change_rate,
               interval_h, last_cheapest
        FROM routes_queue
        WHERE origin = ? AND dest = ? AND airline = ?
        """,
        [origin, dest, airline],
    ).fetchone()
    if not row:
        return None
    return dict(
        zip(
            [
                "origin",
                "dest",
                "airline",
                "priority_tier",
                "search_count",
                "last_scraped_at",
                "next_scrape_at",
                "decayed_demand",
                "last_search_at",
                "change_rate",
                "interval_h",
                "last_cheapest",
            ],
            row,
            strict=False,
        )
    )


def get_top_routes_by_search_count(airline: str, limit: int) -> list[dict[str, Any]]:
    """Top routes for an airline by demand (search_count desc), for the cash scraper's
    daily selection. `airline` is the scraper slug (e.g. "alaska"). Stable tiebreak on
    origin/dest. Scraper-only."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT origin, dest
        FROM routes_queue
        WHERE airline = ?
        ORDER BY search_count DESC, origin ASC, dest ASC
        LIMIT ?
        """,
        [airline, limit],
    ).fetchall()
    return [dict(zip(["origin", "dest"], r, strict=False)) for r in rows]


def is_route_stale(origin: str, dest: str, airline: str | None = None) -> bool:
    """
    Return True if the route has no fresh data — either never scraped,
    or all its flights are expired. When ``airline`` (program IATA code, e.g. "B6")
    is given, staleness is scoped to that airline so one airline's coverage of the
    route doesn't mask another's gap.
    """
    conn = get_connection()
    sql = (
        "SELECT COUNT(*) FROM flights "
        "WHERE origin = ? AND destination = ? AND expires_at_utc > now()"
    )
    params: list[Any] = [origin, dest]
    if airline:
        sql += " AND airline = ?"
        params.append(airline)
    row = conn.execute(sql, params).fetchone()
    return (row[0] if row else 0) == 0


# ---------------------------------------------------------------------------
# Coverage / observability (read-only — powers check_coverage.py)
# ---------------------------------------------------------------------------


def route_coverage(source: str | None = "alaska") -> list[dict[str, Any]]:
    """Per-route coverage: every queued route LEFT JOINed to its future-dated
    flight rows, so routes with zero data still appear (the gaps we care about).

    Ordered fewest-rows-first. `source` filters the joined flights (None = all
    sources); routes_queue itself is not source-tagged so all routes are listed.
    """
    conn = get_connection()
    src_clause = "AND f.source = ?" if source else ""
    params = [source] if source else []
    rows = conn.execute(
        f"""
        SELECT
            q.origin, q.dest, q.airline, q.priority_tier, q.search_count,
            q.last_scraped_at_utc AS last_scraped_at, q.next_scrape_at_utc AS next_scrape_at,
            count(f.id)                            AS flight_rows,
            count(DISTINCT f.date)                 AS dates_covered,
            count(DISTINCT f.cabin_class)          AS cabins_seen,
            string_agg(DISTINCT f.cabin_class, ',') AS cabin_list,
            min(f.date)                            AS first_date,
            max(f.date)                            AS last_date,
            max(f.scraped_at_utc)                  AS last_flight_scrape
        FROM routes_queue q
        LEFT JOIN flights f
               ON f.origin = q.origin
              AND f.destination = q.dest
              AND f.date >= current_date
              {src_clause}
        GROUP BY q.origin, q.dest, q.airline, q.priority_tier, q.search_count,
                 q.last_scraped_at_utc, q.next_scrape_at_utc
        ORDER BY flight_rows ASC,
                 CASE q.priority_tier WHEN 'HIGH' THEN 1 WHEN 'MED' THEN 2 ELSE 3 END
        """,
        params,
    ).fetchall()
    columns = [
        "origin",
        "dest",
        "airline",
        "priority_tier",
        "search_count",
        "last_scraped_at",
        "next_scrape_at",
        "flight_rows",
        "dates_covered",
        "cabins_seen",
        "cabin_list",
        "first_date",
        "last_date",
        "last_flight_scrape",
    ]
    return [dict(zip(columns, row, strict=False)) for row in rows]


def cabin_distribution(source: str | None = "alaska") -> list[dict[str, Any]]:
    """Row / route / date counts per cabin across future-dated flights — a cabin
    that's suddenly absent points at a CABIN_MAP miss or a points<=0 drop."""
    conn = get_connection()
    src_clause = "AND source = ?" if source else ""
    params = [source] if source else []
    rows = conn.execute(
        f"""
        SELECT
            cabin_class,
            count(*)                                        AS rows,
            count(DISTINCT origin || '-' || destination)    AS routes,
            count(DISTINCT date)                            AS dates
        FROM flights
        WHERE date >= current_date
          {src_clause}
        GROUP BY cabin_class
        ORDER BY rows DESC
        """,
        params,
    ).fetchall()
    columns = ["cabin_class", "rows", "routes", "dates"]
    return [dict(zip(columns, row, strict=False)) for row in rows]


# ---------------------------------------------------------------------------
# Bank programs & transfer partners
# ---------------------------------------------------------------------------


def upsert_bank_program(id: int, name: str, short_code: str) -> None:
    """Add or update a bank loyalty currency (e.g. Chase UR, Amex MR)."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO bank_programs (id, name, short_code)
        VALUES (?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            name       = excluded.name,
            short_code = excluded.short_code
        """,
        [id, name, short_code],
    )


def upsert_transfer_partner(
    bank_program_id: int,
    airline_code: str,
    program_name: str,
    transfer_ratio: float = 1.0,
    min_transfer: int = 1000,
    transfer_increment: int = 1000,
) -> None:
    """
    Add or update a bank→airline transfer relationship.

    transfer_ratio: bank points required per 1 airline mile.
        1.0  → 1:1 (1 bank pt = 1 mile)
        3.0  → 3:1 (3 bank pts = 1 mile, e.g. Marriott→Alaska)
    """
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO transfer_partners
            (bank_program_id, airline_code, program_name,
             transfer_ratio, min_transfer, transfer_increment)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (bank_program_id, airline_code) DO UPDATE SET
            program_name       = excluded.program_name,
            transfer_ratio     = excluded.transfer_ratio,
            min_transfer       = excluded.min_transfer,
            transfer_increment = excluded.transfer_increment
        """,
        [
            bank_program_id,
            airline_code,
            program_name,
            transfer_ratio,
            min_transfer,
            transfer_increment,
        ],
    )


def upsert_transfer_bonus(
    bank_program_id: int,
    airline_code: str,
    bonus_pct: int,
    starts_at: date,
    ends_at: date,
    notes: str | None = None,
) -> None:
    """
    Record a transfer bonus offer. Matches on (bank_program_id, airline_code,
    starts_at) so re-running is safe — updates the bonus_pct and end date.
    """
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO transfer_bonuses
            (bank_program_id, airline_code, bonus_pct, starts_at, ends_at, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (bank_program_id, airline_code, starts_at) DO UPDATE SET
            bonus_pct      = excluded.bonus_pct,
            ends_at        = excluded.ends_at,
            notes          = excluded.notes,
            updated_at_utc = now()
        """,
        [bank_program_id, airline_code, bonus_pct, starts_at, ends_at, notes],
    )


def get_transfer_options(airline_code: str, points_cost: int) -> list[dict[str, Any]]:
    """
    Return all bank programs that can transfer to a given airline, with:
      - base points required (points_cost * transfer_ratio)
      - effective points required after any active bonus
      - current bonus details if applicable

    Results ordered by effective_points_needed ASC (best deal first).
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            bp.id                                       AS bank_id,
            bp.name                                     AS bank_name,
            bp.short_code,
            tp.transfer_ratio,
            tp.min_transfer,
            tp.transfer_increment,
            tb.bonus_pct,
            tb.ends_at                                  AS bonus_ends,
            tb.notes                                    AS bonus_notes,
            CEIL(? * tp.transfer_ratio)                 AS base_points_needed,
            CEIL(? * tp.transfer_ratio
                 / (1.0 + COALESCE(tb.bonus_pct, 0) / 100.0))
                                                        AS effective_points_needed
        FROM transfer_partners tp
        JOIN bank_programs bp ON bp.id = tp.bank_program_id
        LEFT JOIN transfer_bonuses tb
            ON  tb.bank_program_id = tp.bank_program_id
            AND tb.airline_code    = tp.airline_code
            AND tb.starts_at      <= current_date
            AND tb.ends_at        >= current_date
        WHERE tp.airline_code = ?
        ORDER BY effective_points_needed ASC
        """,
        [points_cost, points_cost, airline_code],
    ).fetchall()

    columns = [
        "bank_id",
        "bank_name",
        "short_code",
        "transfer_ratio",
        "min_transfer",
        "transfer_increment",
        "bonus_pct",
        "bonus_ends",
        "bonus_notes",
        "base_points_needed",
        "effective_points_needed",
    ]
    return [dict(zip(columns, row, strict=False)) for row in rows]


def get_active_bonuses() -> list[dict[str, Any]]:
    """Return all currently active transfer bonuses across all programs."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            bp.name        AS bank_name,
            bp.short_code,
            tb.airline_code,
            tp.program_name,
            tb.bonus_pct,
            tb.starts_at,
            tb.ends_at,
            tb.notes
        FROM transfer_bonuses tb
        JOIN bank_programs bp ON bp.id = tb.bank_program_id
        LEFT JOIN transfer_partners tp
            ON  tp.bank_program_id = tb.bank_program_id
            AND tp.airline_code    = tb.airline_code
        WHERE tb.starts_at <= current_date
          AND tb.ends_at   >= current_date
        ORDER BY tb.bonus_pct DESC, tb.ends_at ASC
        """
    ).fetchall()

    columns = [
        "bank_name",
        "short_code",
        "airline_code",
        "program_name",
        "bonus_pct",
        "starts_at",
        "ends_at",
        "notes",
    ]
    return [dict(zip(columns, row, strict=False)) for row in rows]
