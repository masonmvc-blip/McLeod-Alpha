import execution.live_engine as live_engine


def test_entry_limit_wait_defaults_to_price_capped_repricing():
    assert live_engine.ENTRY_LIMIT_MAX_WAIT_SECONDS == 0.35
    assert live_engine.ENTRY_REPRICE_MAX_WAIT_SECONDS == 0.35
    assert live_engine.ENTRY_MAX_CHASE_DOLLARS == 0.05
    assert live_engine.ENTRY_MARKET_FALLBACK_ENABLED is False


def test_fresh_preclose_exposure_is_reused_for_entry(monkeypatch):
    monkeypatch.setattr(live_engine, "ENTRY_EXPOSURE_PREFLIGHT_MAX_AGE_SECONDS", 5.0)
    monkeypatch.setattr(live_engine, "time", type("Clock", (), {"time": staticmethod(lambda: 100.0)}))
    monkeypatch.setattr(live_engine, "check_spy_option_exposure", lambda: (False, None))
    live_engine._entry_exposure_preflight = None
    live_engine._last_entry_exposure_preflight_epoch = 0.0

    live_engine.preflight_entry_exposure()

    assert live_engine._fresh_entry_exposure_preflight() == (False, None)
