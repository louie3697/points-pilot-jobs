"""Unit test for the AA spike's response classifier (pure; no browser)."""

import aa_spike


def test_classify_data():
    assert aa_spike._classify(200, '{"slices":[{"x":1}]}') == "DATA"


def test_classify_empty_309():
    assert aa_spike._classify(200, '{"error":"309","slices":[]}') == "EMPTY_309"


def test_classify_empty_no_slices():
    assert aa_spike._classify(200, '{"slices":[]}') == "EMPTY"


def test_classify_blocked_statuses_and_challenge():
    assert aa_spike._classify(403, "x") == "BLOCKED"
    assert aa_spike._classify(None, "") == "BLOCKED"
    assert aa_spike._classify(200, "<html>Access Denied</html>") == "BLOCKED"
    assert aa_spike._classify(200, '{"cpr_chlge":"true"}') == "BLOCKED"
    assert aa_spike._classify(200, "not json") == "BLOCKED"
