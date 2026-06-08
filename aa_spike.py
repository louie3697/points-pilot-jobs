"""Throwaway AA award feasibility spike (jobs repo).

Question: does a warmed Chrome session on a GH Actions (Azure) IP clear AA's Akamai + session so
the JSON itinerary API returns real award data (vs the `309` session-less refusal)? Tries:
  A. warm aa.com + in-page fetch POST /booking/api/search/itinerary
  B. if A is 309/empty, navigate the booking search page to mint a session, then re-fetch
Classifies each attempt, saves the raw JSON, and runs it through the parked american.py parser.
Prints + saves only — NO DB writes. Reuses BrowserScraper's launch/warm machinery.
"""

import asyncio
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path


class _SuppressHashlibWarnings(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "blake2" not in record.getMessage()


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger().handlers[0].addFilter(_SuppressHashlibWarnings())
logger = logging.getLogger("aa_spike")

_API_URL = "https://www.aa.com/booking/api/search/itinerary"
_BOOKING_URL = "https://www.aa.com/booking/find-flights"
ORIGIN, DEST = "SEA", "JFK"
TRAVEL = date.today() + timedelta(days=14)


def _classify(status, text: str) -> str:
    """DATA | EMPTY_309 | EMPTY | BLOCKED — from an AA itinerary-API response."""
    text = text or ""
    if status is None or (isinstance(status, int) and status >= 400):
        return "BLOCKED"
    if "Access Denied" in text or '"cpr_chlge"' in text:
        return "BLOCKED"
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return "BLOCKED"
    if not isinstance(data, dict):
        return "BLOCKED"
    if str(data.get("error")) == "309":
        return "EMPTY_309"
    return "DATA" if data.get("slices") else "EMPTY"


async def _raw_fetch(tab, body: dict) -> dict:
    """In-page POST to the AA itinerary API; returns raw {status, text} (no block handling)."""
    headers = {"content-type": "application/json", "accept": "application/json, text/plain, */*"}
    js = (
        "(async () => {"
        f"  const r = await fetch({json.dumps(_API_URL)}, {{"
        "     method: 'POST',"
        f"    headers: {json.dumps(headers)},"
        f"    body: JSON.stringify({json.dumps(body)}),"
        "     credentials: 'include'"
        "  });"
        "  const t = await r.text();"
        "  return JSON.stringify({ status: r.status, text: t });"
        "})()"
    )
    out = await tab.evaluate(js, await_promise=True)
    if not isinstance(out, str):
        return {"status": None, "text": ""}
    try:
        return json.loads(out)
    except (ValueError, TypeError):
        return {"status": None, "text": ""}


async def _run() -> None:
    from scrapers.american import AmericanScraper, _build_search_request
    from scrapers.browser import BrowserScraper

    class _AALauncher(BrowserScraper):
        airline_code = "AA"
        program_name = "AAdvantage"
        source = "american"
        warm_url = "https://www.aa.com/"
        nav_wait_s = 8.0

        async def fetch_raw(self, o, d, t):  # unused; the spike drives fetches manually
            return {}

        def normalize(self, *a):
            return []

    body = _build_search_request(ORIGIN, DEST, TRAVEL)
    scraper = _AALauncher()
    chosen = {"status": None, "text": ""}
    try:
        tab = await scraper._ensure_browser()  # spawns Chrome + warms aa.com

        a = await _raw_fetch(tab, body)
        cls_a = _classify(a.get("status"), a.get("text"))
        logger.info("ATTEMPT A: http=%s class=%s body=%.180s", a.get("status"), cls_a, a.get("text"))
        chosen = a

        if cls_a in ("EMPTY_309", "EMPTY", "BLOCKED"):
            logger.info("Attempt A not DATA — navigating booking search to mint a session...")
            await tab.get(_BOOKING_URL)
            await tab.sleep(8)
            b = await _raw_fetch(tab, body)
            cls_b = _classify(b.get("status"), b.get("text"))
            logger.info("ATTEMPT B: http=%s class=%s body=%.180s", b.get("status"), cls_b, b.get("text"))
            if cls_b == "DATA":
                chosen = b
    finally:
        scraper.close()

    Path("captures").mkdir(exist_ok=True)
    Path("captures/aa_spike_SEA-JFK.json").write_text(chosen.get("text") or "")

    try:
        data = json.loads(chosen.get("text") or "")
    except (ValueError, TypeError):
        data = {}
    recs = AmericanScraper().normalize(data if isinstance(data, dict) else {}, ORIGIN, DEST, TRAVEL)
    logger.info("PARSER: %d FlightRecords from the chosen response", len(recs))
    for r in recs[:6]:
        logger.info("  %s %s mi  %s  stops=%s", r.cabin_class, r.points_cost, r.raw_flight_number, r.stops)
    final = _classify(chosen.get("status"), chosen.get("text"))
    logger.info("=== AA SPIKE VERDICT: %s, %d records ===", final, len(recs))


def main() -> None:
    try:
        from config import settings  # noqa: F401 — env validation
    except RuntimeError as exc:
        logger.critical("Configuration error: %s", exc)
        sys.exit(1)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
