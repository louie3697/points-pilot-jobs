"""Turkish Airlines Miles&Smiles award availability scraper.

Runs on the BrowserScraper (nodriver/Chrome) transport: turkishairlines.com is blocked to plain
httpx at the TLS/HTTP-2 fingerprint level AND fronted by PerimeterX, but an in-page fetch() inside
a warmed turkishairlines.com Chrome session clears both from a GitHub Actions (Azure) datacenter
IP (proven 2026-06-16). Canonical home for the Turkish browser scraper; run on a daily GH Actions
cron in this (points-pilot-jobs) repo, like Delta/Southwest.

Endpoint: the public dotcom award-availability API ``/api/v1/availability`` — no login. The award
search is keyed by ``moduleType: "AWARD"``; the "session" headers (X-conversationId / X-clientId /
X-requestId) are client-generated UUIDs the API accepts as-is (no server-side session mint needed).
A SINGLE search returns one option per itinerary under
``data.originDestinationInformationList[0].originDestinationOptionList[]``; each option's
``fareCategory`` holds the per-cabin pricing (``ECONOMY``/``BUSINESS`` →
``bookingPriceInfoList[0].referencePassengerFare.totalFare`` in MILE).
(NB: ``option.startingPrice`` is only the cheapest cabin — using it stamps the economy price on
business too, so we read ``fareCategory`` per cabin instead.) ``segmentList[]`` carries the legs.

Everything (the in-page fetch + PerimeterX-428 retry) runs inside a SINGLE tab.evaluate per scrape:
nodriver 0.50.3 + websockets trip "cannot call get() concurrently" across multiple CDP ops in one
scrape, so we keep it to one. The browser transport (warm session, pacing) is from BrowserScraper.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config.airport_tz import AIRPORT_TZ
from config.settings import TTL_HOURS, PriorityTier
from scrapers.base import FlightRecord, ScraperBlockedError
from scrapers.browser import BrowserScraper

logger = logging.getLogger(__name__)

_API_URL = "https://www.turkishairlines.com/api/v1/availability"

# fareCategory key (== bookingPriceInfo cabinType) → our canonical cabin_class.
_CABIN_MAP: dict[str, str] = {
    "ECONOMY": "economy",
    "PREMIUMECONOMY": "premium_economy",
    "PREMIUM_ECONOMY": "premium_economy",
    "PREMIUM": "premium_economy",
    "BUSINESS": "business",
    "FIRST": "first",
}


_SAFE_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}")
_SAFE_CODE = re.compile(r"[A-Za-z0-9_.:-]{1,40}")
_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
)
_PROVIDER_FIELDS = ("code", "errorCode", "errorStatus", "status", "statusCode")
_SECRET_HINTS = ("secret", "token", "bearer", "cookie", "authorization", "password")
_PERIMETERX_BLOCK_KEYS = frozenset(
    {
        "altBlockScript",
        "appId",
        "blockScript",
        "customLogo",
        "firstPartyEnabled",
        "hostUrl",
        "jsClientSrc",
        "uuid",
        "vid",
    }
)


def _safe_primitive(value: object) -> str | None:
    """Render only code-like primitive values; reject UUIDs and secret-shaped strings."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return str(value)
    if isinstance(value, str):
        lowered = value.lower()
        if (
            _SAFE_CODE.fullmatch(value)
            and not _UUID.fullmatch(value)
            and not any(hint in lowered for hint in _SECRET_HINTS)
        ):
            return value
    return None


class _ResponsePayload(dict):
    """Parsed provider JSON carrying body-free HTTP metadata into ``normalize``."""

    def __init__(self, payload: dict, http_status: object) -> None:
        super().__init__(payload)
        self.http_status = (
            http_status if isinstance(http_status, int) and not isinstance(http_status, bool)
            else None
        )


class TurkishResponseError(RuntimeError):
    """Typed, bounded Turkish response failure with no raw response or request data."""

    def __init__(
        self, category: str, *, status: object = None, payload: object = None
    ) -> None:
        self.category = category
        safe_status = status if isinstance(status, int) and not isinstance(status, bool) else None
        parts = [f"category={category}"]
        if safe_status is not None:
            parts.append(f"http_status={safe_status}")
        if isinstance(payload, dict):
            keys = sorted(
                key for key in payload if isinstance(key, str) and _SAFE_KEY.fullmatch(key)
            )[:20]
            parts.append(f"keys=[{','.join(keys)}]")
            data_type = type(payload["data"]).__name__ if "data" in payload else "missing"
            parts.append(f"data_type={data_type}")
            provider = []
            for field in _PROVIDER_FIELDS:
                if field not in payload:
                    continue
                rendered = _safe_primitive(payload[field])
                if rendered is not None:
                    provider.append(f"{field}={rendered}")
            if provider:
                parts.append(f"provider=[{','.join(provider)}]")
        super().__init__(f"Turkish response failure ({', '.join(parts)})"[:320])


def _is_perimeterx_block_envelope(payload: dict, status: object) -> bool:
    """Match only the controlled 403 envelope observed from Turkish's PerimeterX edge."""
    return status == 403 and frozenset(payload) == _PERIMETERX_BLOCK_KEYS


def _parse_tk_dt(s: object, iata: str) -> datetime | None:
    """Parse Turkish's "DD-MM-YYYY HH:MM" local airport time as a tz-aware datetime at `iata`.

    Like Delta, Turkish reports naive local airport times; we attach the airport's IANA zone so
    the stored instant is correct. Returns None on failure or unmapped airport (foreign
    destinations are often unmapped — the time is simply dropped, not fatal)."""
    if not isinstance(s, str) or not s:
        return None
    tz = AIRPORT_TZ.get(iata.upper())
    if tz is None:
        return None
    try:
        return datetime.strptime(s.strip(), "%d-%m-%Y %H:%M").replace(tzinfo=ZoneInfo(tz))
    except (ValueError, TypeError):
        return None


def _flight_number(seg: dict) -> str | None:
    """"TK 12" from a segment's flightCode {airlineCode, flightNumber}."""
    fc = seg.get("flightCode")
    if not isinstance(fc, dict):
        return None
    code = fc.get("airlineCode")
    num = fc.get("flightNumber")
    if not code or num is None:
        return None
    try:
        return f"{code} {int(num)}"
    except (TypeError, ValueError):
        return f"{code} {num}"


def _cabin_miles(info: object) -> int | None:
    """Pull the award miles for one fareCategory cabin entry, or None if unpriced/cash."""
    if not isinstance(info, dict):
        return None
    bpi_list = info.get("bookingPriceInfoList") or []
    if not bpi_list or not isinstance(bpi_list[0], dict):
        return None
    total = ((bpi_list[0].get("referencePassengerFare") or {}).get("totalFare")) or {}
    if total.get("currencyCode") != "MILE":
        return None
    amount = total.get("amount")
    return int(amount) if isinstance(amount, (int, float)) and amount > 0 else None


class TurkishScraper(BrowserScraper):
    """Scraper for Turkish Airlines Miles&Smiles award availability (no login)."""

    airline_code = "TK"
    program_name = "Miles&Smiles"
    source = "turkish"

    # Browser transport: warm the award-booking page once per run (seeds PerimeterX + cookies),
    # then in-page fetch the availability API. Headful under xvfb — PX scores headless harshly.
    # NB: warm on the booking page, NOT the homepage — the homepage's persistent connections hang
    # nodriver's navigation (proven 2026-06-16); the booking page loads to readyState=complete.
    warm_url = "https://www.turkishairlines.com/en-us/miles-and-smiles/book-award-tickets/"
    headless = False
    nav_wait_s = 12.0  # let the PerimeterX sensor run + settle before the first fetch

    # On the Azure IP, PerimeterX challenges the availability call with an HTTP 428 crypto
    # challenge (``sec-cp-challenge``); PX's own JS solves it in the background within a few
    # seconds, after which a retry returns data. Retry in-page up to this many times.
    _px_retries = 4
    _px_wait_s = 10.0

    # Conservative cadence (mirrors Delta): light window, gentle pacing.
    min_delay_s = 8.0
    block_threshold = 4
    refresh_interval_min = 360  # 6 hours
    scrape_days_ahead = 21
    dense_days = 10
    sparse_step = 4
    max_routes_per_run = 12

    def _ensure_loop(self):
        """Drive the browser on nodriver's OWN event loop. nodriver binds its CDP connection
        reader to ``uc.loop()``; using BrowserScraper's default fresh ``new_event_loop()`` trips
        ``cannot call get() concurrently`` on multi-route runs. Align with nodriver's loop."""
        import nodriver as uc

        if self._loop is None or self._loop.is_closed():
            self._loop = uc.loop()
            asyncio.set_event_loop(self._loop)
        return self._loop

    def _build_js(self, origin: str, dest: str, travel_date: date) -> str:
        """One self-contained in-page async script: a single AWARD availability fetch (the
        response carries every cabin's price in fareCategory), retrying PerimeterX 428 challenges.
        Returns a small transport envelope containing the response status + raw response text, or
        a body-free failure category. ONE tab.evaluate per scrape — see the module docstring on
        the nodriver concurrent-recv constraint."""
        date_str = travel_date.strftime("%d-%m-%Y")
        return (
            "(async () => {"
            f"  const URL={json.dumps(_API_URL)};"
            f"  const O={json.dumps(origin.upper())}, D={json.dumps(dest.upper())},"
            f" DT={json.dumps(date_str)};"
            f"  const RETRIES={self._px_retries}, WAIT={int(self._px_wait_s * 1000)};"
            "   const uuid=()=>crypto.randomUUID();"
            "   const sleep=ms=>new Promise(r=>setTimeout(r,ms));"
            "   const hdrs=()=>({'Accept':'application/json','Content-Type':'application/json',"
            "     'Accept-Language':'en','X-clientId':uuid(),'X-requestId':uuid(),'X-country':'us',"
            "     'X-platform':'WEB','X-conversationId':uuid()});"
            "   const body={selectedBookerSearch:'O',selectedCabinClass:'ECONOMY',"
            "     moduleType:'AWARD',passengerTypeList:[{quantity:1,code:'ADULT'}],"
            "     originDestinationInformationList:[{originAirportCode:O,destinationAirportCode:D,"
            "     departureDate:DT}],savedDate:new Date().toISOString()};"
            "   for(let i=0;i<=RETRIES;i++){let r,t;"
            "     try{r=await fetch(URL,{method:'POST',headers:hdrs(),body:JSON.stringify(body),"
            "       credentials:'include'});t=await r.text();}catch(e){"
            "       return JSON.stringify({kind:'transport'});}"
            "     if(r.status===428||t.indexOf('sec-cp-challenge')>=0){"
            "       if(i<RETRIES){await sleep(WAIT);continue;}"
            "       return JSON.stringify({kind:'challenge',status:r.status});}"
            "     return JSON.stringify({kind:'response',status:r.status,text:t});}"
            "   return JSON.stringify({kind:'challenge'});"
            "})()"
        )

    async def fetch_raw(self, origin: str, dest: str, travel_date: date) -> dict:
        """Run one in-page availability fetch and return a parsed API response.

        Transport, exhausted challenge, and JSON failures raise a bounded typed diagnostic. Raw
        bodies, headers, cookies, and generated request identifiers are never copied into it.
        """
        tab = await self._ensure_browser()
        await asyncio.sleep(random.uniform(self.min_delay_s, self.min_delay_s * 2))  # pacing
        out = await tab.evaluate(self._build_js(origin, dest, travel_date), await_promise=True)
        if not isinstance(out, str):
            raise TurkishResponseError("transport")
        try:
            wire = json.loads(out)
        except (ValueError, TypeError):
            raise TurkishResponseError("non_json") from None
        if not isinstance(wire, dict):
            raise TurkishResponseError("non_json")

        kind = wire.get("kind")
        status = wire.get("status")
        if kind == "challenge":
            raise TurkishResponseError("challenge", status=status)
        if kind == "transport":
            raise TurkishResponseError("transport")
        if kind != "response":
            raise TurkishResponseError("transport", status=status)

        response_text = wire.get("text")
        if not isinstance(response_text, str):
            raise TurkishResponseError("non_json", status=status)
        try:
            data = json.loads(response_text)
        except (ValueError, TypeError):
            raise TurkishResponseError("non_json", status=status) from None
        if not isinstance(data, dict):
            raise TurkishResponseError("missing_envelope", status=status)
        return _ResponsePayload(data, status)

    def normalize(
        self, raw: dict, origin: str, dest: str, travel_date: date
    ) -> list[FlightRecord]:
        """Map the availability response → FlightRecords: one per (itinerary × priced cabin)."""
        status = getattr(raw, "http_status", None)
        if not isinstance(raw, dict):
            raise TurkishResponseError("missing_envelope", status=status)
        if _is_perimeterx_block_envelope(raw, status):
            raise ScraperBlockedError("Turkish PerimeterX block envelope (status=403)")
        if isinstance(status, int) and not 200 <= status < 300:
            category = "unsuccessful" if raw.get("success") is False else "http_error"
            raise TurkishResponseError(category, status=status, payload=raw)
        if raw.get("success") is False:
            raise TurkishResponseError("unsuccessful", status=status, payload=raw)
        data = raw.get("data")
        if not isinstance(data, dict):
            raise TurkishResponseError("missing_envelope", status=status, payload=raw)
        od_list = data.get("originDestinationInformationList")
        if not isinstance(od_list, list) or not od_list or not isinstance(od_list[0], dict):
            raise TurkishResponseError("missing_envelope", status=status, payload=raw)
        options = od_list[0].get("originDestinationOptionList")
        if not isinstance(options, list):
            raise TurkishResponseError("missing_envelope", status=status, payload=raw)

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=TTL_HOURS[PriorityTier.MED])
        seen: dict[tuple[str, str], FlightRecord] = {}  # (flight_no, cabin) — dedup brand dups

        for opt in options:
            if not isinstance(opt, dict):
                raise TurkishResponseError("malformed_options", status=status, payload=raw)
            segments = opt.get("segmentList")
            fares = opt.get("fareCategory")
            malformed_segments = (
                not isinstance(segments, list)
                or not segments
                or any(not isinstance(segment, dict) for segment in segments)
            )
            malformed_fares = not isinstance(fares, dict) or not fares
            if malformed_segments or malformed_fares:
                raise TurkishResponseError("malformed_options", status=status, payload=raw)
            try:
                for rec in self._records_for_option(
                    opt, origin, dest, travel_date, now, expires_at
                ):
                    seen.setdefault((rec.raw_flight_number, rec.cabin_class), rec)
            except Exception:  # noqa: BLE001 — convert parser drift to a body-free diagnostic
                raise TurkishResponseError(
                    "malformed_options", status=status, payload=raw
                ) from None
        return list(seen.values())

    def _records_for_option(
        self, opt: dict, origin: str, dest: str, travel_date: date,
        now: datetime, expires_at: datetime,
    ) -> list[FlightRecord]:
        segs = [s for s in (opt.get("segmentList") or []) if isinstance(s, dict)]
        if not segs:
            return []

        # itinerary-level fields, shared across this option's cabins
        stops = max(0, len(segs) - 1)
        dep_time = _parse_tk_dt(segs[0].get("departureDateTime"), origin)
        arr_time = _parse_tk_dt(segs[-1].get("arrivalDateTime"), dest)
        duration_mins: int | None = None
        if dep_time and arr_time:
            d = int((arr_time - dep_time).total_seconds() / 60)
            duration_mins = d if d > 0 else None
        nums = [n for n in (_flight_number(s) for s in segs) if n]
        raw_fn = "+".join(nums) if nums else "UNKNOWN"
        aircraft = segs[0].get("equipmentCode")
        aircraft_str = aircraft[:10] if isinstance(aircraft, str) and aircraft else None
        layovers = [
            s.get("arrivalAirportCode") for s in segs[:-1]
            if isinstance(s.get("arrivalAirportCode"), str)
        ]
        layover_str = ",".join(layovers) if layovers else None
        seats = opt.get("lastSeatCount")
        seats_int = int(seats) if isinstance(seats, int) and seats >= 0 else -1
        operating = {
            s.get("carrierAirline") for s in segs if isinstance(s.get("carrierAirline"), str)
        }
        partner = next((c for c in operating if c and c != self.airline_code), None)
        next_day = bool(arr_time and arr_time.date() > travel_date)

        # one record per priced cabin in fareCategory (correct per-cabin miles, not startingPrice)
        records: list[FlightRecord] = []
        for cab_key, info in (opt.get("fareCategory") or {}).items():
            cabin = _CABIN_MAP.get(str(cab_key).upper())
            if cabin is None:
                continue
            miles = _cabin_miles(info)
            if miles is None:
                continue
            brand = (info.get("bookingPriceInfoList") or [{}])[0].get("brandCode")
            fare_class = brand[:10] if isinstance(brand, str) and brand else None
            try:
                records.append(
                    FlightRecord(
                        origin=origin.upper(),
                        destination=dest.upper(),
                        date=travel_date,
                        airline=self.airline_code,
                        program=self.program_name,
                        source=self.source,
                        points_cost=miles,
                        cash_cost=0.0,  # taxes/fees not in availability (priced at booking)
                        cabin_class=cabin,
                        stops=stops,
                        available_seats=seats_int,
                        scraped_at_utc=now,
                        expires_at_utc=expires_at,
                        raw_flight_number=raw_fn,
                        partner_airline=partner,
                        departure_time_local=dep_time,
                        arrival_time_local=arr_time,
                        duration_minutes=duration_mins,
                        aircraft_type=aircraft_str,
                        is_saver=False,
                        fare_class=fare_class,
                        layover_airports=layover_str,
                        layover_duration_minutes=None,
                        next_day_arrival=next_day,
                        mixed_cabin=False,
                    )
                )
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "[TK] dropping invalid %s record %s→%s: %s", cabin, origin, dest, exc
                )
        return records
