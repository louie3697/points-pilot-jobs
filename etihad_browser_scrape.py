"""Standalone Etihad Guest award browser scrape for the points-pilot-jobs runner.

GitHub's Azure runner IPs clear Etihad's Akamai + Imperva ABP where Fly/httpx can't, so the
nodriver browser scrape runs here (like Delta/Southwest/Turkish). Drives the public award
deep-link per US↔AUH route over a near-term date window in one warmed Chrome session, extracts the
rendered fare-selection cards (DOM-scraped — see scrapers/etihad.py), normalizes, and upserts into
MotherDuck `flights`, then exits. Manual workflow_dispatch or daily cron. Tunable via env:
ETIHAD_SCRAPE_DAYS (default 3); single-route on-demand mode via ETIHAD_ROUTE_ORIGIN/DEST/DATES.
"""

import logging
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

ETIHAD_HEARTBEAT_URL = os.getenv("ETIHAD_HEARTBEAT_URL", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("etihad_browser_scrape")

# US gateways ↔ Abu Dhabi (both directions scraped). Routes Etihad doesn't operate simply return
# no cards (harmless empty); these are the long-standing + current US gateways.
ETIHAD_ROUTES: list[tuple[str, str]] = [
    ("JFK", "AUH"),
    ("ORD", "AUH"),
    ("IAD", "AUH"),
    ("BOS", "AUH"),
    ("LAX", "AUH"),
]
SCRAPE_DAYS = int(os.getenv("ETIHAD_SCRAPE_DAYS", "3"))  # near-term window, scraped every day

# On-demand single-route mode (workflow_dispatch inputs); empty in the daily cron.
ROUTE_ORIGIN = os.getenv("ETIHAD_ROUTE_ORIGIN", "").strip()
ROUTE_DEST = os.getenv("ETIHAD_ROUTE_DEST", "").strip()
ROUTE_DATES = os.getenv("ETIHAD_ROUTE_DATES", "").strip()

# Cron sharding: split ETIHAD_ROUTES across N parallel runs on separate runner IPs (defaults to a
# single unsharded run). Single-route on-demand mode ignores sharding (only shard 0 works).
SHARDS = max(1, int(os.getenv("ETIHAD_SHARDS", "1")))
SHARD_INDEX = int(os.getenv("ETIHAD_SHARD_INDEX", "0"))


def _parse_dates_csv(csv: str) -> list[date]:
    out: list[date] = []
    for tok in csv.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(date.fromisoformat(tok))
        except ValueError:
            logger.warning("ignoring invalid date %r in ETIHAD_ROUTE_DATES", tok)
    return out


def _build_plan(
    route_origin: str,
    route_dest: str,
    route_dates_csv: str,
    scrape_days: int,
    today: date,
    shard_index: int = 0,
    shards: int = 1,
) -> tuple[list[tuple[str, str]], list[date]]:
    """(pairs, dates) for this run — single-route mode if origin+dest given, else cron stride."""
    if route_origin and route_dest:
        if shard_index != 0:
            return [], []
        dates = _parse_dates_csv(route_dates_csv) or [
            today + timedelta(days=i) for i in range(scrape_days)
        ]
        return [(route_origin.upper(), route_dest.upper())], dates

    if bool(route_origin) != bool(route_dest):
        logger.warning(
            "partial route (origin=%r dest=%r) — running cron mode", route_origin, route_dest
        )

    pairs: list[tuple[str, str]] = []
    for origin, dest in ETIHAD_ROUTES[shard_index::shards]:
        pairs.append((origin, dest))
        pairs.append((dest, origin))
    dates = [today + timedelta(days=i) for i in range(scrape_days)]
    return pairs, dates


def _ping_heartbeat() -> None:
    if not ETIHAD_HEARTBEAT_URL:
        return
    try:
        urllib.request.urlopen(ETIHAD_HEARTBEAT_URL, timeout=10).close()
    except Exception as exc:  # noqa: BLE001 — monitoring must never break the run
        logger.warning("heartbeat ping failed: %s", exc)


def _etihad_freshness() -> dict:
    try:
        from db.connection import get_connection

        total, newest = (
            get_connection()
            .execute("SELECT count(*), max(scraped_at_utc) FROM flights WHERE source = 'etihad'")
            .fetchone()
        )
        age_h = None
        if newest is not None:
            if newest.tzinfo is None:
                newest = newest.replace(tzinfo=timezone.utc)
            age_h = round((datetime.now(timezone.utc) - newest).total_seconds() / 3600, 1)
        return {"etihad_rows": int(total or 0), "etihad_newest_age_h": age_h}
    except Exception as exc:  # noqa: BLE001
        logger.warning("freshness snapshot failed: %s", exc)
        return {}


def main() -> None:
    try:
        from config.settings import PriorityTier  # noqa: F401 — also triggers env validation
    except RuntimeError as exc:
        logger.critical("Configuration error: %s", exc)
        sys.exit(1)

    from db.connection import close_connection
    from db.queries import upsert_flights
    from db.schema import migrate
    from pipeline.normalizer import filter_valid, stamp_expiry
    from pipeline.obs import install_log_shipping, ship_metric
    from scrapers.base import ScraperBlockedError
    from scrapers.etihad import EtihadScraper

    install_log_shipping("point-pilot-etihad")
    migrate()
    logger.info("Schema ready")

    pairs, dates = _build_plan(
        ROUTE_ORIGIN, ROUTE_DEST, ROUTE_DATES, SCRAPE_DAYS, date.today(), SHARD_INDEX, SHARDS
    )
    if ROUTE_ORIGIN and ROUTE_DEST:
        logger.info("On-demand mode: %s→%s × %d dates", ROUTE_ORIGIN, ROUTE_DEST, len(dates))
    else:
        logger.info(
            "Cron mode (shard %d/%d): %d routes × %d dates",
            SHARD_INDEX, SHARDS, len(pairs), len(dates),
        )

    scraper = EtihadScraper()
    started = time.monotonic()
    total = 0
    error_count = 0
    routes_scraped = 0
    blocked = False
    try:
        for origin, dest in pairs:
            if blocked:
                break
            route_recs = 0
            for travel in dates:
                try:
                    recs = scraper.scrape(origin, dest, travel)
                except ScraperBlockedError as exc:
                    logger.warning("blocked (%s) — aborting run (rows so far persist)", exc)
                    blocked = True
                    break
                except Exception as exc:  # noqa: BLE001 — one route/date must not sink the run
                    logger.error("Error scraping %s→%s %s: %s", origin, dest, travel, exc)
                    error_count += 1
                    continue
                stamped = stamp_expiry(filter_valid(recs), PriorityTier.MED)
                if stamped:
                    upsert_flights(stamped)
                    route_recs += len(stamped)
                    total += len(stamped)
            routes_scraped += 1
            logger.info("%s→%s: %d records", origin, dest, route_recs)
    finally:
        scraper.close()
        close_connection()

    duration_s = round(time.monotonic() - started, 1)
    ship_metric(
        {
            "event": "scrape_run",
            "service": "point-pilot-etihad",
            "airline": "EY",
            "due_routes": len(pairs),
            "routes_scraped": routes_scraped,
            "records": total,
            "errors": error_count,
            "duration_s": duration_s,
            "blocked": blocked,
            **_etihad_freshness(),
        }
    )
    _ping_heartbeat()
    logger.info(
        "=== done — %d Etihad records upserted (routes=%d errors=%d blocked=%s) in %ss ===",
        total, routes_scraped, error_count, blocked, duration_s,
    )


if __name__ == "__main__":
    main()
    # nodriver leaves keepalive/aclose tasks on its loop that keep the interpreter alive, so the
    # process never exits and the GH Actions step hangs until timeout. main() has already
    # scraped/upserted/shipped its metric, so flush briefly then hard-exit (same as delta/turkish).
    time.sleep(3)
    os._exit(0)
