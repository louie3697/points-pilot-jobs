"""Standalone Delta SkyMiles award browser scrape for the points-pilot-jobs runner.

Delta's award site is Akamai-walled to Fly/httpx (HTTP 444), so the nodriver browser scrape runs
here on GitHub's Azure runner IPs (which clear Akamai). Scrapes popular Delta hub routes over a
near-term date window via one warmed Chrome session (in-page availability fetch — see
``scrapers/delta.py``), normalizes, and upserts into MotherDuck ``flights``, then exits. Suitable
for a manual workflow_dispatch or a cron. Tunable via env: DELTA_SCRAPE_DAYS (default 5);
single-route on-demand mode via DELTA_ROUTE_ORIGIN/DEST/DATES; cron sharding via DELTA_SHARDS /
DELTA_SHARD_INDEX (Delta's ~27-leg Akamai ceiling → the cron shards across parallel runner IPs).

The run plan + scrape loop + metric + heartbeat are shared — see ``browser_scrape_common.py``.
"""

import logging
import os
import sys
import time
from datetime import date

import browser_scrape_common as common

DELTA_HEARTBEAT_URL = os.getenv("DELTA_HEARTBEAT_URL", "")  # optional GH-Actions run heartbeat

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("delta_browser_scrape")

DELTA_ROUTES: list[tuple[str, str]] = [
    # existing ATL megahub + transcons
    ("ATL", "LAX"),
    ("ATL", "MCO"),
    ("ATL", "LGA"),
    ("JFK", "LAX"),
    ("ATL", "SEA"),
    ("ATL", "DEN"),
    ("ATL", "FLL"),
    ("ATL", "BOS"),
    ("LAX", "SEA"),
    ("ATL", "DFW"),
    # MSP hub (serves the 0-result demand from the search logs)
    ("MSP", "JFK"),
    ("MSP", "SEA"),
    ("MSP", "HNL"),
    ("MSP", "LAX"),
    ("MSP", "ATL"),
    ("MSP", "DTW"),
    ("MSP", "MCO"),
    ("MSP", "LAS"),
    ("MSP", "DEN"),
    ("MSP", "BOS"),
    # DTW + SLC hubs
    ("DTW", "ATL"),
    ("DTW", "LAX"),
    ("DTW", "MCO"),
    ("DTW", "LGA"),
    ("SLC", "ATL"),
    ("SLC", "SEA"),
]
SCRAPE_DAYS = int(os.getenv("DELTA_SCRAPE_DAYS", "5"))  # near-term window, scraped every day

# On-demand single-route mode (set by the workflow_dispatch inputs). Empty in the daily cron.
ROUTE_ORIGIN = os.getenv("DELTA_ROUTE_ORIGIN", "").strip()
ROUTE_DEST = os.getenv("DELTA_ROUTE_DEST", "").strip()
ROUTE_DATES = os.getenv("DELTA_ROUTE_DATES", "").strip()

# Cron sharding: split DELTA_ROUTES across N parallel runs on separate runner IPs (the GH Actions
# matrix sets these) so the per-run leg count stays under Delta's Akamai ceiling.
SHARDS = max(1, int(os.getenv("DELTA_SHARDS", "1")))
SHARD_INDEX = int(os.getenv("DELTA_SHARD_INDEX", "0"))


def _parse_dates_csv(csv: str):  # re-exported for tests
    return common.parse_dates_csv(csv, logger)


def _build_plan(route_origin, route_dest, route_dates_csv, scrape_days, today,
                shard_index=0, shards=1):  # re-exported for tests
    return common.build_plan(
        DELTA_ROUTES, route_origin, route_dest, route_dates_csv, scrape_days, today,
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
    from scrapers.delta import DeltaScraper

    install_log_shipping("point-pilot-delta")  # ship WARNING+ logs to Better Stack
    migrate()  # idempotent; ensures the flights table exists
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
        DeltaScraper(), pairs, dates,
        source="delta", service="point-pilot-delta", airline="DL",
        heartbeat_url=DELTA_HEARTBEAT_URL, logger=logger,
    )


if __name__ == "__main__":
    main()
    # nodriver leaves a pending asyncio task (Connection.aclose) after browser teardown that keeps
    # the interpreter alive, so the process never exits on its own and the GitHub Actions step hangs
    # until its timeout. main() has already scraped, upserted, shipped its metric, and pinged the
    # heartbeat by this point, so flush briefly then hard-exit.
    time.sleep(3)
    os._exit(0)
