"""Standalone Southwest Rapid Rewards award browser scrape for the points-pilot-jobs runner.

Southwest's shopping endpoint is gated by an F5/Shape per-request JS sensor that blocks Fly/httpx,
so the nodriver browser scrape runs here on GitHub's Azure runner IPs — a warmed nodriver Chrome
session mints a valid token per in-page fetch (see ``scrapers/southwest.py``). Scrapes popular
focus-city routes (both directions) over a near-term date window, normalizes, and upserts into
MotherDuck ``flights``, then exits. Suitable for a manual workflow_dispatch or a cron. Tunable via
env: SOUTHWEST_SCRAPE_DAYS (default 5); single-route on-demand mode via
SOUTHWEST_ROUTE_ORIGIN/DEST/DATES.

The run plan + scrape loop + metric + heartbeat are shared — see ``browser_scrape_common.py``.
"""

import logging
import os
import sys
import time
from datetime import date

import browser_scrape_common as common

SOUTHWEST_HEARTBEAT_URL = os.getenv("SOUTHWEST_HEARTBEAT_URL", "")  # optional GH-Actions heartbeat

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("southwest_browser_scrape")

SOUTHWEST_ROUTES: list[tuple[str, str]] = [
    # existing focus-city pairs
    ("LAS", "LAX"),
    ("LAS", "OAK"),
    ("DAL", "HOU"),
    ("MDW", "LAS"),
    ("DEN", "PHX"),
    ("BWI", "MCO"),
    ("PHX", "LAS"),
    ("SAN", "LAS"),
    ("DAL", "MDW"),
    ("DEN", "LAS"),
    # DEN / MDW / BWI / PHX focus-city spokes + SEA-LAX (search demand)
    ("DEN", "LAX"),
    ("DEN", "MDW"),
    ("DEN", "BWI"),
    ("DEN", "OAK"),
    ("MDW", "MCO"),
    ("MDW", "BWI"),
    ("BWI", "FLL"),
    ("BWI", "BOS"),
    ("PHX", "LAX"),
    ("PHX", "SAN"),
    ("OAK", "SAN"),
    ("SEA", "LAX"),
]
SCRAPE_DAYS = int(os.getenv("SOUTHWEST_SCRAPE_DAYS", "5"))  # near-term window, scraped every day

# On-demand single-route mode (set by the workflow_dispatch inputs). Empty in the daily cron.
ROUTE_ORIGIN = os.getenv("SOUTHWEST_ROUTE_ORIGIN", "").strip()
ROUTE_DEST = os.getenv("SOUTHWEST_ROUTE_DEST", "").strip()
ROUTE_DATES = os.getenv("SOUTHWEST_ROUTE_DATES", "").strip()

# Cron sharding: split SOUTHWEST_ROUTES across N parallel runs (default single, unsharded).
SHARDS = max(1, int(os.getenv("SOUTHWEST_SHARDS", "1")))
SHARD_INDEX = int(os.getenv("SOUTHWEST_SHARD_INDEX", "0"))


def _parse_dates_csv(csv: str):  # re-exported for tests
    return common.parse_dates_csv(csv, logger)


def _build_plan(route_origin, route_dest, route_dates_csv, scrape_days, today,
                shard_index=0, shards=1):  # re-exported for tests
    return common.build_plan(
        SOUTHWEST_ROUTES, route_origin, route_dest, route_dates_csv, scrape_days, today,
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
    from scrapers.southwest import SouthwestScraper

    install_log_shipping("point-pilot-southwest")
    migrate()
    logger.info("Schema ready")

    pairs, dates = _build_plan(
        ROUTE_ORIGIN, ROUTE_DEST, ROUTE_DATES, SCRAPE_DAYS, date.today(), SHARD_INDEX, SHARDS
    )
    if ROUTE_ORIGIN and ROUTE_DEST:
        logger.info(
            "On-demand single-route mode: %s→%s × %d dates", ROUTE_ORIGIN, ROUTE_DEST, len(dates)
        )
    else:
        logger.info(
            "Cron mode (shard %d/%d): %d routes × %d dates",
            SHARD_INDEX, SHARDS, len(pairs), len(dates),
        )

    common.run_scrape(
        SouthwestScraper(), pairs, dates,
        source="southwest", service="point-pilot-southwest", airline="WN",
        heartbeat_url=SOUTHWEST_HEARTBEAT_URL, logger=logger,
    )


if __name__ == "__main__":
    main()
    # nodriver leaves keepalive/aclose tasks on its loop that keep the interpreter alive, so the
    # process never exits and the GH Actions step hangs until timeout. main() has already
    # scraped/upserted/shipped its metric, so flush briefly then hard-exit.
    time.sleep(3)
    os._exit(0)
