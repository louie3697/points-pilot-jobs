from pathlib import Path

import pytest

import pipeline.obs as obs


def test_flush_then_hard_exit_sleeps_flushes_then_exits(monkeypatch):
    events = []

    monkeypatch.setattr(obs.time, "sleep", lambda seconds: events.append(("sleep", seconds)))
    monkeypatch.setattr(obs, "flush", lambda: events.append(("flush", None)))

    def fake_exit(code):
        events.append(("exit", code))
        raise SystemExit(code)

    monkeypatch.setattr(obs.os, "_exit", fake_exit)

    with pytest.raises(SystemExit) as exc:
        obs.flush_then_hard_exit(7, delay_s=3.0)

    assert exc.value.code == 7
    assert events == [("sleep", 3.0), ("flush", None), ("exit", 7)]


def test_flush_then_hard_exit_skips_sleep_when_delay_is_zero(monkeypatch):
    events = []

    monkeypatch.setattr(obs.time, "sleep", lambda seconds: events.append(("sleep", seconds)))
    monkeypatch.setattr(obs, "flush", lambda: events.append(("flush", None)))

    def fake_exit(code):
        events.append(("exit", code))
        raise SystemExit(code)

    monkeypatch.setattr(obs.os, "_exit", fake_exit)

    with pytest.raises(SystemExit):
        obs.flush_then_hard_exit()

    assert events == [("flush", None), ("exit", 0)]


def test_scraper_hard_exit_entrypoints_use_outcome_exit_code():
    root = Path(__file__).resolve().parents[1]
    expected = {
        "delta_browser_scrape.py": "flush_then_hard_exit(outcome.exit_code, delay_s=3.0)",
        "etihad_browser_scrape.py": "flush_then_hard_exit(outcome.exit_code, delay_s=3.0)",
        "southwest_browser_scrape.py": "flush_then_hard_exit(outcome.exit_code, delay_s=3.0)",
        "turkish_browser_scrape.py": "flush_then_hard_exit(outcome.exit_code, delay_s=3.0)",
        "alaska_scrape.py": "flush_then_hard_exit(outcome.exit_code)",
        "jetblue_scrape.py": "flush_then_hard_exit(outcome.exit_code)",
    }

    for relpath, call in expected.items():
        text = (root / relpath).read_text()
        assert "outcome = main()" in text
        assert call in text
        assert "os._exit(0)" not in text
