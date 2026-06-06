"""Unit tests for transfer_bonuses.py — no network, no MotherDuck required.

parse_bonuses: pure HTML → list[dict], tested with a minimal fixture that mirrors
the frequentmiler.com table structure (4 cols: Transfer From, Transfer Bonus Details,
Start Date, End Date).

reconcile: snapshot-replace logic, tested with an in-memory DuckDB.
"""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from transfer_bonuses import parse_bonuses, reconcile

# ---------------------------------------------------------------------------
# Minimal HTML fixture — mirrors the frequentmiler.com table structure.
# Contains:
#   - one valid airline bonus (Amex → Air France)
#   - one with a different bank label variant (Citi ThankYou Rewards → Qatar)
#   - one hotel destination to skip (Chase → Marriott Bonvoy)
#   - one hotel-only destination to skip (Citi → Preferred Hotels)
#   - one unknown bank to skip (Rove Miles → Air Canada)
# Dates use the real page format: Excel serial prefix + MM/DD/YY.
# ---------------------------------------------------------------------------
HTML_FIXTURE = """\
<html><body>
<table>
<tr>
  <td>Transfer From</td><td>Transfer Bonus Details</td>
  <td>Start Date</td><td>End Date</td>
</tr>
<tr>
  <td>Amex Membership Rewards</td>
  <td>25% transfer bonus from Amex Membership Rewards to Air France KLM Flying Blue</td>
  <td>4617406/02/26</td><td>4620306/30/26</td>
</tr>
<tr>
  <td>Citi ThankYou Rewards</td>
  <td>30% transfer bonus from Citi ThankYou Rewards to Qatar Privilege Club Avios</td>
  <td>4617406/01/26</td><td>4620306/30/26</td>
</tr>
<tr>
  <td>Chase Ultimate Rewards</td>
  <td>55% transfer bonus from Chase Ultimate Rewards to Marriott Bonvoy</td>
  <td>4615805/16/26</td><td>4620306/30/26</td>
</tr>
<tr>
  <td>Citi ThankYou Rewards</td>
  <td>30% transfer bonus from Citi ThankYou Rewards to Preferred Hotels &amp; Resorts I Prefer</td>
  <td>4615905/17/26</td><td>4618606/13/26</td>
</tr>
<tr>
  <td>Rove Miles</td>
  <td>25% transfer bonus from Rove Miles to Air Canada Aeroplan</td>
  <td>4614905/07/26</td><td>4617906/06/26</td>
</tr>
</table>
</body></html>
"""

TODAY = date(2026, 6, 6)


# ---------------------------------------------------------------------------
# parse_bonuses tests
# ---------------------------------------------------------------------------

def test_parse_valid_bonus():
    """Amex Membership Rewards → Air France: pct, dates, and notes parsed correctly."""
    records = parse_bonuses(HTML_FIXTURE, today=TODAY)
    amex_af = next((r for r in records if r["airline_code"] == "AF"), None)
    assert amex_af is not None
    assert amex_af["bank_program_id"] == 2       # Amex Membership Rewards
    assert amex_af["bonus_pct"] == 25
    assert amex_af["starts_at"] == date(2026, 6, 2)   # real date from page, not TODAY
    assert amex_af["ends_at"] == date(2026, 6, 30)
    assert amex_af["notes"] is None


def test_parse_date_prefix_stripped():
    """Excel serial prefix in date cells (e.g. '4617406/02/26') is stripped correctly."""
    records = parse_bonuses(HTML_FIXTURE, today=TODAY)
    # Citi → QR has start '4617406/01/26' → 2026-06-01, end '4620306/30/26' → 2026-06-30
    qatar = next((r for r in records if r["airline_code"] == "QR"), None)
    assert qatar is not None
    assert qatar["bank_program_id"] == 4         # Citi ThankYou Rewards
    assert qatar["bonus_pct"] == 30
    assert qatar["starts_at"] == date(2026, 6, 1)
    assert qatar["ends_at"] == date(2026, 6, 30)


def test_parse_hotel_destination_skipped():
    """'Marriott Bonvoy' and 'Preferred Hotels' as destinations → skipped."""
    records = parse_bonuses(HTML_FIXTURE, today=TODAY)
    # Only AF and QR survive from this fixture
    assert len(records) == 2
    codes = {r["airline_code"] for r in records}
    assert codes == {"AF", "QR"}


def test_parse_unknown_bank_skipped():
    """'Rove Miles' is not in BANK_MAP → its row is silently skipped (isolated fixture)."""
    html = """\
<html><body>
<table>
<tr><td>Transfer From</td><td>Transfer Bonus Details</td><td>Start Date</td><td>End Date</td></tr>
<tr>
  <td>Rove Miles</td>
  <td>25% transfer bonus from Rove Miles to Air Canada Aeroplan</td>
  <td>4614905/07/26</td><td>4617906/06/26</td>
</tr>
</table>
</body></html>
"""
    records = parse_bonuses(html, today=TODAY)
    assert records == []


def test_parse_no_table_raises():
    """If the page has no <table>, raise ValueError — structure changed."""
    with pytest.raises(ValueError, match="No <table>"):
        parse_bonuses("<html><body><p>nothing here</p></body></html>", today=TODAY)


# ---------------------------------------------------------------------------
# reconcile tests — in-memory DuckDB, no MotherDuck needed
# ---------------------------------------------------------------------------

@pytest.fixture()
def mem_conn():
    """In-memory DuckDB seeded with the minimal schema and two transfer_partners rows."""
    conn = duckdb.connect(":memory:")
    conn.execute("SET TimeZone='UTC'")
    conn.execute("CREATE SEQUENCE IF NOT EXISTS transfer_bonuses_id_seq")
    conn.execute("""
        CREATE TABLE transfer_partners (
            bank_program_id  SMALLINT     NOT NULL,
            airline_code     VARCHAR(10)  NOT NULL,
            PRIMARY KEY (bank_program_id, airline_code)
        )
    """)
    conn.execute("""
        CREATE TABLE transfer_bonuses (
            id               BIGINT      PRIMARY KEY DEFAULT nextval('transfer_bonuses_id_seq'),
            bank_program_id  SMALLINT    NOT NULL,
            airline_code     VARCHAR(10) NOT NULL,
            bonus_pct        INTEGER     NOT NULL CHECK (bonus_pct > 0),
            starts_at        DATE        NOT NULL,
            ends_at          DATE        NOT NULL,
            notes            VARCHAR,
            created_at_utc   TIMESTAMP   NOT NULL DEFAULT now(),
            updated_at_utc   TIMESTAMP   NOT NULL DEFAULT now(),
            CHECK (ends_at >= starts_at),
            UNIQUE (bank_program_id, airline_code, starts_at)
        )
    """)
    # Two tracked airlines: AS (Alaska) and AF (Air France)
    conn.execute("INSERT INTO transfer_partners (bank_program_id, airline_code) VALUES (5, 'AS')")
    conn.execute("INSERT INTO transfer_partners (bank_program_id, airline_code) VALUES (2, 'AF')")
    return conn


def test_reconcile_replaces_existing(mem_conn):
    """Existing bonus is deleted; fresh record is inserted."""
    mem_conn.execute(
        "INSERT INTO transfer_bonuses "
        "(bank_program_id, airline_code, bonus_pct, starts_at, ends_at) "
        "VALUES (5, 'AS', 30, '2026-01-01', '2026-01-31')"
    )
    assert mem_conn.execute("SELECT COUNT(*) FROM transfer_bonuses").fetchone()[0] == 1

    fresh = [{
        "bank_program_id": 2,       # Amex
        "airline_code": "AF",
        "bonus_pct": 25,
        "starts_at": date(2026, 6, 2),
        "ends_at": date(2026, 6, 30),
        "notes": None,
    }]
    deleted, inserted = reconcile(mem_conn, fresh)
    assert deleted == 1
    assert inserted == 1
    rows = mem_conn.execute(
        "SELECT bank_program_id, airline_code, bonus_pct FROM transfer_bonuses"
    ).fetchall()
    assert rows == [(2, "AF", 25)]


def test_reconcile_zero_bonuses_clears_table(mem_conn):
    """Empty records list → DELETE fires, nothing inserted. Valid (no active bonuses)."""
    mem_conn.execute(
        "INSERT INTO transfer_bonuses "
        "(bank_program_id, airline_code, bonus_pct, starts_at, ends_at) "
        "VALUES (5, 'AS', 30, '2026-01-01', '2026-01-31')"
    )
    deleted, inserted = reconcile(mem_conn, [])
    assert deleted == 1
    assert inserted == 0
    assert mem_conn.execute("SELECT COUNT(*) FROM transfer_bonuses").fetchone()[0] == 0


def test_reconcile_dry_run_leaves_table_unchanged(mem_conn):
    """--dry-run: no DB changes, returns (0, 0)."""
    mem_conn.execute(
        "INSERT INTO transfer_bonuses "
        "(bank_program_id, airline_code, bonus_pct, starts_at, ends_at) "
        "VALUES (5, 'AS', 30, '2026-01-01', '2026-01-31')"
    )
    fresh = [{
        "bank_program_id": 2, "airline_code": "AF", "bonus_pct": 25,
        "starts_at": date(2026, 6, 2), "ends_at": date(2026, 6, 30), "notes": None,
    }]
    deleted, inserted = reconcile(mem_conn, fresh, dry_run=True)
    assert (deleted, inserted) == (0, 0)
    # Table unchanged — stale AS bonus still present
    assert mem_conn.execute("SELECT COUNT(*) FROM transfer_bonuses").fetchone()[0] == 1
