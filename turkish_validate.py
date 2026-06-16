"""Validation harness for the Turkish Miles&Smiles scraper (no DB write).

Runs TurkishScraper against a few US→IST routes on the GitHub Actions (Azure) IP and prints the
records, to confirm end-to-end award-data extraction works (warm session + in-page availability
fetch clears the TLS-fingerprint + PerimeterX wall). Exits non-zero if no records come back.
Imports require MOTHERDUCK_TOKEN to be set (import-time settings gate) — set it to a dummy; this
script never touches the DB.
"""

import logging
import sys
from datetime import date, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("turkish_validate")

from scrapers.turkish import TurkishScraper  # noqa: E402 (after logging config)

ROUTES = [("SEA", "IST"), ("JFK", "IST"), ("ORD", "IST")]


def main() -> None:
    base = date.today() + timedelta(days=21)
    dates = [base, base + timedelta(days=3)]
    sc = TurkishScraper()
    total = 0
    try:
        for origin, dest in ROUTES:
            for dt in dates:
                try:
                    recs = sc.scrape(origin, dest, dt)
                except Exception as exc:  # noqa: BLE001
                    log.error("scrape %s-%s %s FAILED: %s", origin, dest, dt, exc)
                    continue
                total += len(recs)
                log.info("%s-%s %s -> %d records", origin, dest, dt, len(recs))
                for r in recs[:4]:
                    log.info(
                        "    %-9s %s->%s  %6d pts  seats=%s stops=%s dep=%s  %s",
                        r.cabin_class,
                        r.origin,
                        r.destination,
                        r.points_cost,
                        r.available_seats,
                        r.stops,
                        r.departure_time_local,
                        r.raw_flight_number,
                    )
    finally:
        sc.close()

    log.info("TOTAL records across all routes/dates: %d", total)
    if total == 0:
        log.error("VALIDATION FAILED — 0 records (wall block or API/parse change?)")
        sys.exit(1)
    log.info("VALIDATION OK ✓")


if __name__ == "__main__":
    main()
