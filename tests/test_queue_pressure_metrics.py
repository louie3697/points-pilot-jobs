from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import browser_scrape_common as common
from config.settings import PriorityTier
from pipeline.queue_manager import QueueManager
from pp_db import autocommit as db


def test_get_due_batch_reports_actual_due_backlog_beyond_limit(monkeypatch):
    queue = QueueManager(scraper=None)
    due_rows = [
        {
            "origin": f"O{i:02d}",
            "dest": f"D{i:02d}",
            "airline": "delta",
            "priority_tier": PriorityTier.MED,
            "search_count": 0,
            "last_scraped_at": datetime(2026, 6, 18, tzinfo=timezone.utc),
            "next_scrape_at": datetime(2026, 6, 18, tzinfo=timezone.utc),
            "decayed_demand": 0.0,
            "last_search_at": None,
            "change_rate": 0.0,
            "interval_h": None,
            "last_cheapest": None,
        }
        for i in range(4)
    ]
    monkeypatch.setattr(db, "count_due_routes", lambda airline=None: 6)
    monkeypatch.setattr(db, "get_due_routes", lambda limit, airline=None: due_rows)

    batch = queue.get_due_batch(limit=4, airline="delta")

    assert len(batch) == 4
    assert {job.queue_due_count for job in batch} == {6}


def test_build_queue_plan_preserves_actual_due_backlog_from_queue_manager(monkeypatch):
    fake_jobs = [
        SimpleNamespace(origin=f"O{i}", dest=f"D{i}", queue_due_count=6) for i in range(4)
    ]

    class _FakeQueueManager:
        def __init__(self, scraper=None):
            pass

        def seed_from_config(self):
            pass

        def get_due_batch(self, limit, airline=None):
            assert limit == 4
            assert airline == "delta"
            return fake_jobs

    monkeypatch.setattr("pipeline.queue_manager.QueueManager", _FakeQueueManager)

    route_jobs, dates = common.build_queue_plan(
        "delta",
        shard_index=0,
        shards=2,
        max_legs=2,
        scrape_days=1,
        today=date(2026, 6, 18),
    )

    assert len(route_jobs) == 2
    assert [job.queue_due_count for job in route_jobs] == [6, 6]
    assert dates == [date(2026, 6, 18)]
