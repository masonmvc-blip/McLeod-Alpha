from datetime import datetime

from execution.live_engine import Position
from execution.option_quote_telemetry import build_option_management_cycle


def _position():
    return Position(
        direction="CALL", entry_price=750.0, stop_price=749.0, target_price=752.0,
        quantity=2, opened=datetime(2026, 7, 27, 10, 0), reason="TEST",
        option_symbol="SPY  260731C00750000", option_entry=5.0, option_stop=4.8,
        schwab_order_id="entry-1", schwab_fill_price=5.01,
        schwab_fill_timestamp="2026-07-27T10:00:01-04:00",
        option_high_since_entry=5.6, option_low_since_entry=4.7,
        option_trailing_high_bid=5.55,
    )


def test_management_cycle_captures_executable_quote_cost_and_excursion_facts():
    event = build_option_management_cycle(
        _position(), spy_price=751.0, bid=5.4, ask=5.5, mark=5.45, last=5.48,
        quote_metadata={"quote_age_seconds": 0.2, "quote_source": "schwab_direct_option_quote"},
        action="UPDATE_STOP", reason="4% Stop", observed_at=datetime(2026, 7, 27, 10, 2),
    )

    assert event["executable_exit_price"] == 5.4
    assert event["executable_exit_source"] == "bid"
    assert event["spread_dollars"] == 0.1
    assert event["estimated_exit_spread_cost_dollars"] == 20.0
    assert event["mfe_pct_live"] == 12.0
    assert event["mae_pct_live"] == -6.0
    assert event["option_trailing_high_bid"] == 5.55
    assert event["decision_reason"] == "4% Stop"


def test_terminal_event_carries_the_broker_exit_order_identifier():
    event = build_option_management_cycle(
        _position(), spy_price=751.0, mark=5.4, action="EXIT", reason="STOP",
        event_type="option_trade_closed", broker_exit_order_id="exit-1",
    )

    assert event["event_type"] == "option_trade_closed"
    assert event["broker_exit_order_id"] == "exit-1"
