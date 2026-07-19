from utils.decision_contract import normalize_reason_text, reason_code_from_text, quote_state_from_age


def test_normalize_market_closed_variants():
    assert normalize_reason_text("Market closed") == "Market Closed"
    assert normalize_reason_text("Outside regular market hours") == "Market Closed"


def test_reason_code_mapping():
    assert reason_code_from_text("Market closed") == "MARKET_CLOSED"
    assert reason_code_from_text("Startup stale candle guard") == "STARTUP_GUARD"


def test_quote_state_from_age():
    assert quote_state_from_age(None, max_stale_seconds=1800, refresh_seconds=3) == "UNAVAILABLE"
    assert quote_state_from_age(1.0, max_stale_seconds=1800, refresh_seconds=3) == "FRESH"
    assert quote_state_from_age(8.0, max_stale_seconds=1800, refresh_seconds=3) == "DELAYED"
    assert quote_state_from_age(2000.0, max_stale_seconds=1800, refresh_seconds=3) == "STALE"
