"""
Normalizer: cross-record validation and freshness stamping.

Sits between the scraper layer (raw HTTP → FlightRecord) and the DB layer.
Each scraper handles its own field mapping; the normalizer handles data quality
and computes TTL-aware expires_at based on the route's tier.

This module is shared across all scrapers — no airline-specific logic here.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from config.settings import TTL_HOURS
from scrapers.base import FlightRecord

logger = logging.getLogger(__name__)


def build_expires_at(tier: str, scraped_at: datetime) -> datetime:
    """
    Compute expires_at based on the route's priority tier and TTL config.

    Args:
        tier: PriorityTier.HIGH | MED | LOW
        scraped_at: UTC timestamp of when the data was fetched

    Returns:
        UTC datetime when this record should be considered stale.
    """
    ttl_h = TTL_HOURS.get(tier, TTL_HOURS["LOW"])
    return scraped_at + timedelta(hours=ttl_h)


def stamp_expiry(records: list[FlightRecord], tier: str) -> list[FlightRecord]:
    """
    Return new FlightRecord objects with expires_at set based on tier TTL.

    Scrapers set expires_at to a default MED TTL. This function corrects it
    for routes with HIGH or LOW tiers before writing to DB.
    """
    if not records:
        return []

    # If all records already have the right TTL, skip (avoids unnecessary copies)
    sample_ttl = TTL_HOURS.get(tier, TTL_HOURS["LOW"])
    expected_delta = timedelta(hours=sample_ttl)
    first = records[0]
    if abs((first.expires_at_utc - first.scraped_at_utc) - expected_delta).total_seconds() < 60:
        return records  # already correct within 1 minute

    return [replace(r, expires_at_utc=build_expires_at(tier, r.scraped_at_utc)) for r in records]


def validate_record(record: FlightRecord) -> bool:
    """
    Return True if the record passes basic sanity checks.
    Validation errors are logged as warnings (not raised).
    """
    from datetime import date as date_type

    if len(record.origin) != 3 or not record.origin.isupper():
        logger.warning("Invalid origin: %r", record.origin)
        return False
    if len(record.destination) != 3 or not record.destination.isupper():
        logger.warning("Invalid destination: %r", record.destination)
        return False
    if record.origin == record.destination:
        logger.warning("Origin == destination: %r", record.origin)
        return False
    if isinstance(record.date, date_type):
        days_past = (datetime.now(timezone.utc).date() - record.date).days
        if days_past > 1:
            # Past by more than a day → a genuinely bogus scrape worth surfacing.
            logger.warning("Flight date is in the past: %s", record.date)
            return False
        if days_past == 1:
            # Expected: the window is anchored at run start, and a long run crosses UTC
            # midnight, so a day-0 date rolls one day past mid-run. Normal housekeeping.
            logger.debug("Flight date rolled past run-start, dropping: %s", record.date)
            return False
    if record.points_cost <= 0:
        logger.warning("Non-positive points_cost: %d", record.points_cost)
        return False
    return True


def filter_valid(records: list[FlightRecord]) -> list[FlightRecord]:
    """Filter out invalid records, logging a summary of rejections."""
    from datetime import date as date_type

    valid = [r for r in records if validate_record(r)]
    dropped = len(records) - len(valid)
    if dropped:
        # A drop count fully explained by just-rolled-past dates is expected housekeeping
        # (see validate_record), not an anomaly — keep it at DEBUG so genuine drops stand out.
        today = datetime.now(timezone.utc).date()
        rolled = sum(
            1 for r in records if isinstance(r.date, date_type) and (today - r.date).days == 1
        )
        level = logging.DEBUG if rolled == dropped else logging.WARNING
        logger.log(level, "Dropped %d invalid records out of %d", dropped, len(records))
    return valid
