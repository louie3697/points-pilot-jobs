"""Phase 3: Delta per-shard leg cap raised to use its proven per-session WAF headroom."""


def test_delta_max_legs_per_shard_is_18():
    from config.settings import CRON_MAX_LEGS_PER_SHARD

    assert CRON_MAX_LEGS_PER_SHARD["delta"] == 18
    # Southwest stays at 20: its WAF blocks by IP reputation (not leg count), so a generous cap
    # maximizes the clean shards' coverage (a 10 cap was tried and reduced total coverage).
    assert CRON_MAX_LEGS_PER_SHARD["southwest"] == 20
    assert CRON_MAX_LEGS_PER_SHARD["turkish"] == 20
    assert CRON_MAX_LEGS_PER_SHARD["etihad"] == 20
