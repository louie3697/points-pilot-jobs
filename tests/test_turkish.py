import os
from datetime import date

os.environ.setdefault("MOTHERDUCK_TOKEN", "test-dummy-token")

from scrapers.turkish import (  # noqa: E402 — env var must be set before this import
    TurkishScraper,
    _flight_number,
    _parse_tk_dt,
)

TRAVEL = date(2026, 7, 7)


def _opt(price=55000, currency="MILE", segs=None, seats=4, brand="ECOFLY"):
    segs = segs or [
        {
            "departureAirportCode": "JFK",
            "arrivalAirportCode": "IST",
            "departureDateTime": "07-07-2026 00:25",
            "arrivalDateTime": "07-07-2026 17:15",
            "flightCode": {"airlineCode": "TK", "flightNumber": "0012"},
            "stopCount": 0,
            "equipmentCode": "77W",
            "carrierAirline": "TK",
        }
    ]
    return {
        "segmentList": segs,
        "startingPrice": {"currencyCode": currency, "amount": price},
        "lastSeatCount": seats,
        "selectedBrandCode": brand,
    }


def _resp(options):
    return {
        "data": {"originDestinationInformationList": [{"originDestinationOptionList": options}]},
        "success": True,
    }


# ---------------------------------------------------------------- pure helpers
def test_flight_number_strips_leading_zeros():
    assert _flight_number({"flightCode": {"airlineCode": "TK", "flightNumber": "0012"}}) == "TK 12"


def test_flight_number_missing_returns_none():
    assert _flight_number({"flightCode": {}}) is None
    assert _flight_number({}) is None


def test_parse_tk_dt_attaches_origin_timezone():
    dt = _parse_tk_dt("07-07-2026 19:15", "JFK")
    assert dt is not None and dt.tzinfo is not None
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 7, 7, 19, 15)


def test_parse_tk_dt_unmapped_airport_is_none():
    # IST is not in the (US-centric) AIRPORT_TZ map → time dropped, not an error
    assert _parse_tk_dt("07-07-2026 17:15", "IST") is None
    assert _parse_tk_dt("", "JFK") is None


# ---------------------------------------------------------------- normalize
def test_normalize_nonstop_economy_and_business():
    raw = {"economy": _resp([_opt()]), "business": _resp([_opt(price=135000)])}
    recs = TurkishScraper().normalize(raw, "JFK", "IST", TRAVEL)
    assert {r.cabin_class for r in recs} == {"economy", "business"}
    eco = next(r for r in recs if r.cabin_class == "economy")
    assert eco.origin == "JFK" and eco.destination == "IST"
    assert eco.airline == "TK" and eco.source == "turkish" and eco.program == "Miles&Smiles"
    assert eco.points_cost == 55000
    assert eco.stops == 0 and eco.raw_flight_number == "TK 12"
    assert eco.available_seats == 4
    assert eco.departure_time_local is not None  # JFK is mapped
    biz = next(r for r in recs if r.cabin_class == "business")
    assert biz.points_cost == 135000


def test_normalize_connection_sets_stops_and_layover():
    segs = [
        {
            "departureAirportCode": "ORD", "arrivalAirportCode": "IST",
            "departureDateTime": "07-07-2026 21:55", "arrivalDateTime": "08-07-2026 16:30",
            "flightCode": {"airlineCode": "TK", "flightNumber": "0006"}, "carrierAirline": "TK",
        },
        {
            "departureAirportCode": "IST", "arrivalAirportCode": "BKK",
            "departureDateTime": "08-07-2026 20:10", "arrivalDateTime": "09-07-2026 09:25",
            "flightCode": {"airlineCode": "TK", "flightNumber": "0068"}, "carrierAirline": "TK",
        },
    ]
    raw = {"economy": _resp([_opt(segs=segs)]), "business": {"data": None, "success": False}}
    recs = TurkishScraper().normalize(raw, "ORD", "BKK", TRAVEL)
    assert len(recs) == 1
    r = recs[0]
    assert r.stops == 1
    assert r.layover_airports == "IST"
    assert r.raw_flight_number == "TK 6+TK 68"


def test_normalize_skips_non_mile_and_zero_price():
    raw = {
        "economy": _resp([_opt(currency="USD"), _opt(price=0)]),
        "business": {"data": None, "success": False},
    }
    assert TurkishScraper().normalize(raw, "JFK", "IST", TRAVEL) == []


def test_normalize_handles_perimeterx_challenge_and_empty():
    # a 428 PX challenge body (no "data") and a soft-empty success:false both yield no records
    sc = TurkishScraper()
    assert sc.normalize({"economy": {"sec-cp-challenge": "true"}}, "JFK", "IST", TRAVEL) == []
    assert sc.normalize({"economy": {"data": None, "success": False}}, "JFK", "IST", TRAVEL) == []
    assert sc.normalize({}, "JFK", "IST", TRAVEL) == []


# ---------------------------------------------------------------- request builder
def test_build_js_encodes_award_route_and_date():
    js = TurkishScraper()._build_js("JFK", "IST", TRAVEL)
    assert "moduleType" in js and "AWARD" in js
    assert '"JFK"' in js and '"IST"' in js
    assert "07-07-2026" in js
    assert "/api/v1/availability" in js
