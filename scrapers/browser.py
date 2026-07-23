"""nodriver (real Chrome via CDP) transport base for scrapers behind Akamai.

Sibling to HttpScraper. Owns one Chrome + its own asyncio loop, launched lazily on the first
scrape() and reused for every scrape() in a refresh run; close() tears it down (the scheduler
always calls close() at the end of a run). Subclasses implement `async def fetch_raw()`
(build request -> await self._page_fetch(...)) and a sync normalize().

Transport (proven by the 2026-06-07 spike): run the GraphQL POST as an in-page fetch() inside
a warmed site session — this clears Akamai from a datacenter IP where plain httpx gets 444.
nodriver's own self-spawn wait is too short for cold Chrome, so we spawn Chrome ourselves,
wait for its CDP port, then uc.start(host, port) to connect to the existing instance.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import shutil
import subprocess
import tempfile
import time
import urllib.request
from abc import abstractmethod
from datetime import date

from scrapers.base import BaseScraper, FlightRecord, ScraperBlockedError

logger = logging.getLogger(__name__)


class BrowserScraper(BaseScraper):
    """BaseScraper + a nodriver Chrome transport (warmed session + in-page fetch)."""

    # --- transport config (override per airline) ---
    warm_url: str | None = None  # navigated once per browser to seed anti-bot cookies
    headless: bool = False  # headful under xvfb on Fly/CI — Akamai scores headless harshly
    nav_wait_s: float = 8.0  # dwell after warm navigation (let the Akamai sensor settle)
    cdp_port_timeout_s: float = 90.0  # wait for Chrome's CDP port (cold start on a small VM ~30s+)

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._browser = None  # nodriver Browser
        self._tab = None  # warmed tab
        self._chrome_proc: subprocess.Popen | None = None
        self._profile_dir: str | None = None
        self._consecutive_blocks = 0  # streak of WAF blocks → circuit breaker

    # ------------------------------------------------------------------ lifecycle
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            # Register as this thread's loop so nodriver's Browser.stop() (which calls
            # asyncio.get_event_loop()) targets our loop for a clean CDP teardown.
            asyncio.set_event_loop(self._loop)
        return self._loop

    async def _launch(self) -> None:
        """Spawn Chrome ourselves, wait for the CDP port, then connect nodriver to it."""
        import nodriver as uc
        from nodriver.core.config import find_chrome_executable
        from nodriver.core.util import free_port

        port = free_port()
        self._profile_dir = tempfile.mkdtemp(prefix=f"{self.source}_browser_")
        flags = [
            "--remote-allow-origins=*",  # REQUIRED: Chrome rejects the CDP ws upgrade without it
            "--remote-debugging-host=127.0.0.1",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={self._profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-service-autorun",
            "--homepage=about:blank",
            "--no-pings",
            "--password-store=basic",
            "--disable-breakpad",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--disable-session-crashed-bubble",
            "--disable-search-engine-choice-screen",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-sandbox",  # required on Fly/CI (root); harmless locally
        ]
        if self.headless:
            flags.append("--headless=new")
        self._chrome_proc = subprocess.Popen(
            [find_chrome_executable(), *flags],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        version_url = f"http://127.0.0.1:{port}/json/version"
        deadline = time.monotonic() + self.cdp_port_timeout_s
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(version_url, timeout=1).read()
                break
            except Exception:  # noqa: BLE001 — port not up yet
                await asyncio.sleep(0.5)
        else:
            raise RuntimeError(f"[{self.source}] Chrome CDP port {port} never opened")
        self._browser = await uc.start(host="127.0.0.1", port=port)
        self._tab = await self._browser.get(self.warm_url or "about:blank")
        if self.warm_url:
            await self._tab.sleep(self.nav_wait_s)
        logger.info("[%s] browser launched + warmed (%s)", self.source, self.warm_url)

    async def _ensure_browser(self):
        if self._browser is None:
            await self._launch()
        return self._tab

    async def _page_fetch(self, url: str, body: dict, extra_headers: dict[str, str]) -> dict:
        """POST `body` to `url` via fetch() inside the warmed page; returns parsed JSON dict.

        Paces before the request, then routes the response through _check_blocked (which raises
        ScraperBlockedError after `block_threshold` consecutive WAF blocks).
        """
        tab = await self._ensure_browser()
        await asyncio.sleep(random.uniform(self.min_delay_s, self.min_delay_s * 2))
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            **extra_headers,
        }
        js = (
            "(async () => {"
            f"  const res = await fetch({json.dumps(url)}, {{"
            "     method: 'POST',"
            f"    headers: {json.dumps(headers)},"
            f"    body: JSON.stringify({json.dumps(body)}),"
            "     credentials: 'include'"
            "  });"
            "  const text = await res.text();"
            "  return JSON.stringify({ status: res.status, text: text });"
            "})()"
        )
        out = await tab.evaluate(js, await_promise=True)
        if not isinstance(out, str):
            # The in-page JS threw (network/CORS error) — tab.evaluate returns an
            # ExceptionDetails object, not our JSON string. Treat as no data this call
            # (soft-empty); don't crash and don't touch the block streak.
            logger.warning("[%s] in-page fetch returned non-str (JS error): %r", self.source, out)
            return {}
        return self._check_blocked(json.loads(out))

    def _check_blocked(self, payload: dict) -> dict:
        """Raise ScraperBlockedError on a WAF block/challenge after the threshold; else return
        the parsed JSON dict (or {} for a benign empty / GraphQL-error / non-JSON body)."""
        if not isinstance(payload, dict):
            return {}
        status = payload.get("status")
        text = payload.get("text") or ""
        is_block = (
            (isinstance(status, int) and status in (403, 406, 429, 444))
            or "Access Denied" in text
            or '"cpr_chlge"' in text
        )
        if is_block:
            self._consecutive_blocks += 1
            if self._consecutive_blocks >= self.block_threshold:
                raise ScraperBlockedError(
                    f"{self._consecutive_blocks} consecutive blocks from "
                    f"{self.source} (status={status})"
                )
            return {}
        self._consecutive_blocks = 0
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
        # GraphQL errors-only payload (no "data" key): soft empty, not a WAF block.
        if "errors" in data and "data" not in data:
            return {}
        return data

    # ------------------------------------------------------------------ contract
    def scrape(self, origin: str, dest: str, travel_date: date) -> list[FlightRecord]:
        """Sync BaseScraper contract: drive the async pipeline on this instance's loop."""
        loop = self._ensure_loop()

        async def _pipeline() -> dict:
            await self._ensure_browser()
            return await self.fetch_raw(origin, dest, travel_date)

        raw = loop.run_until_complete(_pipeline())
        return self.normalize(raw, origin, dest, travel_date)

    @abstractmethod
    async def fetch_raw(self, origin: str, dest: str, travel_date: date) -> dict:
        """Build the request and `return await self._page_fetch(url, body, headers)`."""
        ...

    def close(self) -> None:
        """Tear down browser + Chrome process + temp profile + loop. Best-effort; never raises."""
        loop = self._loop
        browser = self._browser
        tab = self._tab
        if browser is not None and loop is not None and not loop.is_closed():

            async def _close_connections() -> None:
                # nodriver's synchronous Browser.stop() only *schedules* aclose(). Closing our
                # owned loop immediately afterward destroyed that pending coroutine in production.
                # Await each CDP connection directly before terminating Chrome or the loop.
                connections = [tab]
                try:
                    connections.extend(browser.tabs)
                except Exception:  # noqa: BLE001 — teardown remains best-effort
                    pass
                connections.append(browser)
                seen: set[int] = set()
                for connection in connections:
                    if connection is None or id(connection) in seen:
                        continue
                    seen.add(id(connection))
                    aclose = getattr(connection, "aclose", None)
                    if aclose is None:
                        continue
                    try:
                        await aclose()
                    except Exception:  # noqa: BLE001 — continue closing remaining connections
                        pass

            try:
                loop.run_until_complete(_close_connections())
            except Exception:  # noqa: BLE001
                pass
        self._browser = None
        self._tab = None
        if self._chrome_proc is not None:
            try:
                self._chrome_proc.terminate()
                self._chrome_proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    self._chrome_proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._chrome_proc = None
        if self._profile_dir:
            shutil.rmtree(self._profile_dir, ignore_errors=True)
            self._profile_dir = None
        if loop is not None and not loop.is_closed():
            # The loop belongs exclusively to this scraper. Cancel and await any residual
            # nodriver/websocket tasks so loop.close() cannot destroy pending tasks or leak an
            # un-awaited Connection.aclose coroutine.
            try:
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:  # noqa: BLE001 — teardown remains best-effort
                pass
            try:
                loop.close()
            except Exception:  # noqa: BLE001 — close() must never mask the scrape outcome
                pass
        self._loop = None
