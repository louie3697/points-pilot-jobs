"""Azure-IP SUSTAINED-VOLUME probe for the Google Flights cash scraper.

The 4-unit smoke proved Google serves our headful-Chrome scraper from a GitHub-Actions (Azure) IP.
This probe answers the follow-up: does Google RAMP-BLOCK under sustained volume? It scrapes ~150
real route/date/cabin units SERIALLY (like one migration shard would) and reports the fare-success
rate by THIRDS — if Google ramps into walling us, the later thirds degrade and the busy-domestic
detectors stop serving. READ-ONLY: writes nothing to the database.

Terminal shapes:
  * detectors keep serving across all thirds, no block ramp -> PASS (sustained scraping is safe)
  * later thirds collapse / detectors go empty / blocks climb -> RAMP-BLOCK (needs pacing/proxies)
A WATCHDOG force-exits past the deadline so the step always finishes with a readable partial report.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import date, timedelta

try:  # print runtime versions first, flushed, so they survive a hang
    import nodriver as _nd
    import websockets as _ws

    print(f"PROBE env: websockets {_ws.__version__} | nodriver {_nd.__version__}", flush=True)
except Exception as _exc:  # noqa: BLE001
    print(f"PROBE env: version import failed: {_exc!r}", flush=True)

from scrapers.base import ScraperBlockedError
from scrapers.google_flights import GoogleFlightsScraper

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

TODAY = date.today()
DEADLINE_S = 1200  # 20 min hard ceiling; watchdog force-exits past this
results: list[dict] = []  # ordered: {tag, det, n, status}


def _d(days: int) -> date:
    return TODAY + timedelta(days=days)


# Busy domestic, both directions — the wall/ramp detector (MUST keep serving throughout).
DETECTOR_ROUTES = [
    ("SFO", "JFK"), ("JFK", "SFO"), ("ATL", "MCO"), ("MCO", "ATL"),
    ("ORD", "LAX"), ("LAX", "ORD"), ("DFW", "LGA"), ("LGA", "DFW"),
]
OTHER_DOMESTIC = [
    ("SEA", "DEN"), ("DEN", "SEA"), ("BOS", "SFO"), ("SFO", "BOS"),
    ("LAS", "MDW"), ("MDW", "LAS"), ("PHX", "IAH"), ("IAH", "PHX"),
]
INTL = [
    ("JFK", "LHR"), ("LHR", "JFK"), ("SFO", "NRT"), ("LAX", "HND"),
    ("ORD", "CDG"), ("MIA", "GRU"), ("SEA", "LHR"), ("EWR", "FCO"),
    ("BOS", "DUB"), ("IAD", "ICN"), ("ATL", "AMS"), ("JFK", "CDG"),
]
ECON_DATES = [_d(7), _d(12), _d(19), _d(28)]   # near + a far-out (28)
PREM_DATES = [_d(14), _d(40)]                   # incl. far-out 40


def _build_units() -> list[tuple[str, str, date, str, bool]]:
    units: list[tuple[str, str, date, str, bool]] = []
    # economy body: date-outer / route-inner so detectors recur evenly across the whole run
    for dt in ECON_DATES:
        for o, dd in DETECTOR_ROUTES:
            units.append((o, dd, dt, "economy", True))
        for o, dd in OTHER_DOMESTIC + INTL:
            units.append((o, dd, dt, "economy", False))
    # premium tail (intl business + PE) — interleaved across the two dates
    for dt in PREM_DATES:
        for o, dd in INTL:
            units.append((o, dd, dt, "business", False))
        for o, dd in INTL[:8]:
            units.append((o, dd, dt, "premium_economy", False))
    return units


UNITS = _build_units()


def _thirds_report() -> int:
    n = len(results)
    if not n:
        print("\nPROBE VERDICT: DRIVER-BROKEN — no unit completed.", flush=True)
        return 4
    print("\n===== PROBE SUMMARY (by thirds of execution order) =====", flush=True)
    blocked_total = 0
    third_stats = []
    for t in range(3):
        lo, hi = n * t // 3, n * (t + 1) // 3
        seg = results[lo:hi]
        dets = [r for r in seg if r["det"]]
        dets_ok = [r for r in dets if r["n"] > 0]
        served = [r for r in seg if r["n"] > 0]
        blk = [r for r in seg if r["status"] == "BLOCKED"]
        blocked_total += len(blk)
        third_stats.append((len(dets_ok), len(dets), len(served), len(seg), len(blk)))
        print(
            f"  third {t+1}: detectors {len(dets_ok)}/{len(dets)} serving | "
            f"units with fares {len(served)}/{len(seg)} | blocked {len(blk)}",
            flush=True,
        )
    total_served = sum(1 for r in results if r["n"] > 0)
    print(
        f"completed {n}/{len(UNITS)} units | with fares {total_served}/{n} | blocked {blocked_total}",
        flush=True,
    )
    # Verdict: detectors must keep serving in EVERY third and blocks must not climb.
    det_full = all(d_ok == d_tot and d_tot > 0 for d_ok, d_tot, *_ in third_stats)
    last_served_rate = third_stats[-1][2] / max(third_stats[-1][3], 1)
    first_served_rate = third_stats[0][2] / max(third_stats[0][3], 1)
    if det_full and blocked_total == 0 and last_served_rate >= first_served_rate * 0.7:
        print("PROBE VERDICT: PASS — no ramp-block under sustained volume. Cash→GA is safe to build.", flush=True)
        return 0
    if blocked_total > 0 or not third_stats[-1][1] or third_stats[-1][0] == 0 or last_served_rate < first_served_rate * 0.5:
        print("PROBE VERDICT: RAMP-BLOCK — coverage degraded as volume rose. Needs pacing/proxies.", flush=True)
        return 2
    print("PROBE VERDICT: PARTIAL — inspect the thirds table above.", flush=True)
    return 3


def _watchdog() -> None:
    time.sleep(DEADLINE_S)
    print(f"\nPROBE WATCHDOG: {DEADLINE_S}s deadline hit — exiting with partial results.", flush=True)
    _thirds_report()
    os._exit(7)


def main() -> int:
    print(f"PROBE: {len(UNITS)} units, serial, deadline {DEADLINE_S}s", flush=True)
    threading.Thread(target=_watchdog, daemon=True).start()
    scraper = GoogleFlightsScraper()
    t0 = time.monotonic()
    try:
        for i, (o, dd, dt, cabin, det) in enumerate(UNITS, 1):
            tag = f"{o}->{dd} {dt.isoformat()} {cabin}"
            try:
                n = len(scraper.scrape_fares(o, dd, dt, cabin=cabin))
                status = "OK" if n > 0 else "EMPTY"
            except ScraperBlockedError as exc:
                n, status = -1, "BLOCKED"
                print(f"  [{i}/{len(UNITS)}] {tag} -> BLOCKED ({exc})", flush=True)
            except Exception as exc:  # noqa: BLE001
                n, status = -2, "ERROR"
                print(f"  [{i}/{len(UNITS)}] {tag} -> ERROR ({exc!r})", flush=True)
            results.append({"tag": tag, "det": det, "n": n, "status": status})
            # Log detectors, blocks, and a heartbeat every 20 units to keep the signal visible.
            if det or status in ("BLOCKED", "ERROR") or i % 20 == 0:
                print(
                    f"  [{i}/{len(UNITS)}] {tag} -> {n} fares [{status}] "
                    f"({time.monotonic()-t0:.0f}s elapsed)",
                    flush=True,
                )
    finally:
        for closer in ("close", "stop", "shutdown"):
            fn = getattr(scraper, closer, None)
            if callable(fn):
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass
                break
    rc = _thirds_report()
    sys.stdout.flush()
    os._exit(rc)


if __name__ == "__main__":
    main()
