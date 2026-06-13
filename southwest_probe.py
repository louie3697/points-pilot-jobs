"""Southwest datacenter-IP mint probe — can GH Actions / Azure mint a valid Shape token?

Southwest (Rapid Rewards) award search needs no login, but its shopping endpoint is gated by
an F5/Shape Security per-request JS sensor (rotating `ee30zvqlwf-*` headers). httpx replay is a
dead end (the token flaps 200->403 on reuse and won't transfer routes). The only viable path is
nodriver: warm a real search page so Shape's JS hooks fetch(), then do an IN-PAGE fetch() to the
shopping endpoint — Shape auto-attaches a fresh token per call.

This was VALIDATED on a residential IP (3/3 mints -> HTTP 200, ~112 KB award payloads). The ONLY
open question before building a real scraper is the SAME one we asked for Delta/American: does a
datacenter IP (Azure/GH-Actions) mint a token Shape ACCEPTS, or does it get 403'd / challenged?

Run as a manual workflow_dispatch and read the printed verdict + the uploaded screenshot.
Self-contained (only nodriver). Headful under xvfb on CI. Writes NOTHING to MotherDuck.
Exits 0 if >=1 mint returned award data, 1 otherwise (so the run goes red on a block).
"""

import asyncio
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

import nodriver as uc
from nodriver.core.config import find_chrome_executable
from nodriver.core.util import free_port

# Warm one route, mint a DIFFERENT route — proves a fresh token generalizes (not a page replay).
WARM_URL = (
    "https://www.southwest.com/air/booking/select-depart.html"
    "?adultPassengersCount=1&adultsCount=1&departureDate=2026-06-22"
    "&departureTimeOfDay=ALL_DAY&destinationAirportCode=BOS&fareType=POINTS"
    "&int=HOMEQBOMAIR&originationAirportCode=SEA&passengerType=ADULT"
    "&returnDate=&returnTimeOfDay=ALL_DAY&to=BOS&tripType=oneway"
)
SHOP_URL = "https://www.southwest.com/api/air-booking/v1/air-booking/page/air/booking/shopping"
BODY = {
    "adultPassengersCount": "1", "adultsCount": "1", "departureDate": "2026-06-25",
    "departureTimeOfDay": "ALL_DAY", "destinationAirportCode": "LAX", "fareType": "POINTS",
    "int": "HOMEQBOMAIR", "originationAirportCode": "SEA", "passengerType": "ADULT",
    "promoCode": "", "returnDate": "", "returnTimeOfDay": "ALL_DAY", "to": "LAX",
    "tripType": "oneway", "application": "air-booking", "site": "southwest",
}
# Apigee gateway headers. The Shape sensor (ee30zvqlwf-*) is added by Southwest's own JS — we
# must NOT set it; that is the whole point of minting it in a real browser.
HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "content-type": "application/json",
    "x-api-key": "l7xx944d175ea25f4b9c903a583ea82a1c4c",
    "x-app-id": "air-booking",
    "x-channel-id": "southwest",
    "x-user-experience-id": "0f836f7f-ddea-465c-b25c-6c4c79463507",
}
SHOT = "/tmp/southwest_probe.png"
HTML = "/tmp/southwest_probe.html"

MINT_JS = (
    "(async () => {"
    f"  const res = await fetch({json.dumps(SHOP_URL)}, {{"
    "     method: 'POST',"
    f"    headers: {json.dumps(HEADERS)},"
    f"    body: JSON.stringify({json.dumps(BODY)}),"
    "     credentials: 'include'"
    "  });"
    "  const text = await res.text();"
    "  let hasData = false;"
    "  try { hasData = !!JSON.parse(text)?.data?.searchResults?.airProducts?.length; } catch (e) {}"
    "  return JSON.stringify({ status: res.status, len: text.length, hasData,"
    "                          head: text.slice(0, 300) });"
    "})()"
)


async def run() -> int:
    port = free_port()
    profile = tempfile.mkdtemp(prefix="southwest_probe_")
    flags = [
        "--remote-allow-origins=*",
        "--remote-debugging-host=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-search-engine-choice-screen",
        "--homepage=about:blank",
        "--window-size=1400,1000",
        "--no-sandbox",  # required on CI (root)
        "--disable-dev-shm-usage",
    ]
    proc = subprocess.Popen(
        [find_chrome_executable(), *flags],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    try:
        ver = f"http://127.0.0.1:{port}/json/version"
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(ver, timeout=1).read()
                break
            except Exception:  # noqa: BLE001 — port not up yet
                await asyncio.sleep(0.5)
        else:
            print("[probe] FAIL: Chrome CDP port never opened")
            return 1

        browser = await uc.start(host="127.0.0.1", port=port)
        print(f"[probe] warming: {WARM_URL}")
        tab = await browser.get(WARM_URL)
        await tab.sleep(12)  # let Shape JS load + hook fetch; cold CI runner is slow

        cur_url = await tab.evaluate("location.href")
        title = await tab.evaluate("document.title")
        body_head = await tab.evaluate("document.body ? document.body.innerText.slice(0,300) : ''")
        print(f"[probe] warm landed on: {cur_url!r}  title={title!r}")

        # Guard: if we are not actually on southwest.com, this is an ENVIRONMENT failure
        # (wrong tab / didn't navigate), NOT a Shape verdict. Don't emit a false negative.
        if not (isinstance(cur_url, str) and "southwest.com" in cur_url):
            print("[probe] FAIL (environment): warm nav did not land on southwest.com — "
                  "cannot judge the IP. Check for a stray Chrome on the runner.")
            try:
                await tab.save_screenshot(SHOT)
            except Exception:  # noqa: BLE001
                pass
            browser.stop()
            return 1

        warm_challenged = isinstance(body_head, str) and bool(
            re.search(r"are you a human|verify|challenge|access denied|unusual", body_head, re.I)
        )
        if warm_challenged:
            print(f"[probe] ⚠ warm page looks challenged: {body_head!r}")

        results = []
        for i in range(3):
            out = await tab.evaluate(MINT_JS, await_promise=True)
            if isinstance(out, str):
                d = json.loads(out)
                results.append(d)
                tag = "AWARD DATA ✓" if d["hasData"] else d["head"][:120]
                print(f"[probe] mint {i + 1}: HTTP {d['status']} len={d['len']} "
                      f"hasData={d['hasData']} -> {tag}")
            else:
                results.append({"status": "JS_ERROR", "hasData": False})
                print(f"[probe] mint {i + 1}: JS error -> {str(out)[:140]}")
            await tab.sleep(3)

        try:
            await tab.save_screenshot(SHOT)
            html = await tab.get_content()
            with open(HTML, "w") as f:
                f.write(html)
            print(f"[probe] saved {SHOT} + {HTML}")
        except Exception as exc:  # noqa: BLE001
            print(f"[probe] artifact save error: {exc}")

        browser.stop()

        wins = sum(1 for r in results if r.get("hasData"))
        if wins:
            print(f"\n[probe] ✅ SUCCESS from datacenter IP — {wins}/3 mints got award data.")
            print("[probe] => Build Southwest on the Delta browser template here (Azure).")
            return 0
        codes = [r.get("status") for r in results]
        print(f"\n[probe] ❌ NO award data minted from datacenter IP (statuses={codes}).")
        print("[probe] => Shape rejects this IP's token. Fall back to residential egress / proxy.")
        return 1
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
