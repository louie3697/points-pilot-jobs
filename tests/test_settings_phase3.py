"""Phase 3: Delta per-shard leg cap raised to use its proven per-session WAF headroom."""


def test_delta_max_legs_per_shard_is_18():
    from config.settings import CRON_MAX_LEGS_PER_SHARD

    assert CRON_MAX_LEGS_PER_SHARD["delta"] == 18
    # Southwest stays at 20 in code defaults: its WAF blocks by IP reputation (not leg count),
    # so a generous cap maximizes clean-shard coverage. Probe-mode workflow override keeps
    # scheduled jobs low-impact at 1 leg/shard while blocking is active.
    assert CRON_MAX_LEGS_PER_SHARD["southwest"] == 20
    assert CRON_MAX_LEGS_PER_SHARD["turkish"] == 20
    assert CRON_MAX_LEGS_PER_SHARD["etihad"] == 20
