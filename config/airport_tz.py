"""IATA airport → IANA timezone, for rendering award departure_time_local in the ORIGIN
airport's local wall-clock so it matches Google Flights' displayed local time. Covers every
origin in our routes (AS + B6 + DL). Add an entry before onboarding a new origin airport."""

AIRPORT_TZ: dict[str, str] = {
    "ANC": "America/Anchorage",
    "ATL": "America/New_York",
    "BOI": "America/Boise",
    "BOS": "America/New_York",
    "CLT": "America/New_York",
    "DEN": "America/Denver",
    "DFW": "America/Chicago",
    "EWR": "America/New_York",
    "FLL": "America/New_York",
    "GEG": "America/Los_Angeles",
    "IAD": "America/New_York",
    "IAH": "America/Chicago",
    "JFK": "America/New_York",
    "LAS": "America/Los_Angeles",
    "LAX": "America/Los_Angeles",
    "LGA": "America/New_York",
    "MCO": "America/New_York",
    "MIA": "America/New_York",
    "MSP": "America/Chicago",
    "ORD": "America/Chicago",
    "PDX": "America/Los_Angeles",
    "PHX": "America/Phoenix",
    "RDU": "America/New_York",
    "SAN": "America/Los_Angeles",
    "SEA": "America/Los_Angeles",
    "SFO": "America/Los_Angeles",
    "SJC": "America/Los_Angeles",
}
