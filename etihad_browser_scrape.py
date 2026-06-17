"""Standalone Etihad Guest award browser scrape for the points-pilot-jobs runner.

GitHub's Azure runner IPs clear Etihad's Akamai + Imperva ABP where Fly/httpx can't, so the
nodriver browser scrape runs here (like Delta/Southwest/Turkish). Drives the public award
deep-link per US↔AUH route over a near-term date window in one warmed Chrome session, DOM-scrapes
the rendered fare-selection cards (see ``scrapers/etihad.py``), normalizes, and upserts into
MotherDuck ``flights``, then exits. Manual workflow_dispatch or daily cron. Tunable via env:
ETIHAD_SCRAPE_DAYS (default 3); single-route on-demand mode via ETIHAD_ROUTE_ORIGIN/DEST/DATES.

The run plan + scrape loop + metric + heartbeat are shared — see ``browser_scrape_common.py``.
"""

import logging
import os
import sys
import time
from datetime import date

import browser_scrape_common as common

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

# Cron sharding: split ETIHAD_ROUTES across N parallel runs on separate runner IPs (default single).
SHARDS = max(1, int(os.getenv("ETIHAD_SHARDS", "1")))
SHARD_INDEX = int(os.getenv("ETIHAD_SHARD_INDEX", "0"))


def _parse_dates_csv(csv: str):  # re-exported for tests
    return common.parse_dates_csv(csv, logger)


def _build_plan(route_origin, route_dest, route_dates_csv, scrape_days, today,
                shard_index=0, shards=1):  # re-exported for tests
    return common.build_plan(
        ETIHAD_ROUTES, route_origin, route_dest, route_dates_csv, scrape_days, today,
        shard_index, shards, logger,
    )


def main() -> None:
    try:
        from config.settings import PriorityTier  # noqa: F401 — also triggers env validation
    except RuntimeError as exc:
        logger.critical("Configuration error: %s", exc)
        sys.exit(1)

    from db.schema import migrate
    from pipeline.obs import install_log_shipping
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

    common.run_scrape(
        EtihadScraper(), pairs, dates,
        source="etihad", service="point-pilot-etihad", airline="EY",
        heartbeat_url=ETIHAD_HEARTBEAT_URL, logger=logger,
    )


if __name__ == "__main__":
    main()
    # nodriver leaves keepalive/aclose tasks on its loop that keep the interpreter alive, so the
    # process never exits and the GH Actions step hangs until timeout. main() has already
    # scraped/upserted/shipped its metric, so flush briefly then hard-exit (same as delta/turkish).
    time.sleep(3)
    os._exit(0)
