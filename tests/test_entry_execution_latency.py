import execution.live_engine as live_engine


def test_entry_limit_wait_defaults_to_subsecond_market_fallback():
    assert live_engine.ENTRY_LIMIT_MAX_WAIT_SECONDS == 0.35
    assert live_engine.ENTRY_MARKET_FALLBACK_MAX_WAIT_SECONDS == 0.35