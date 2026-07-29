from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from execution.option_quote_telemetry import build_option_management_cycle
from execution.entry_quote_telemetry import attach_entry_quote_telemetry
from strategy.day_trade_spy_shadow_suite import (
    MODEL_VERSION,
    evaluate_day_trade_spy_shadow_suite,
)


ET = ZoneInfo("America/New_York")


def _candles(*, opening=True):
    start = "2026-07-29 09:40" if opening else "2026-07-29 11:00"
    index = pd.date_range(start, periods=10, freq="min", tz=ET)
    rows = []
    for offset, timestamp in enumerate(index):
        close = 600.00 + offset * 0.04
        rows.append({
            "datetime": timestamp,
            "open": close - 0.02,
            "high": close + 0.06,
            "low": close - 0.06,
            "close": close,
            "volume": 1000 + offset * 20,
            "ema10": close - 0.02,
            "ema20": close - 0.05,
            "vwap": close - 0.03,
        })
    return pd.DataFrame(rows).set_index("datetime")


def _features():
    return {
        "direction": "CALL",
        "support_resistance": {
            "nearest_resistance": 601.0,
            "distance_to_resistance_pct": 0.10,
        },
    }


def _option():
    return {
        "symbol": "SPY   260731C00600000",
        "bid": 1.00,
        "ask": 1.04,
        "mark": 1.02,
        "volume": 500,
        "open_interest": 250,
    }


def test_suite_is_explicitly_shadow_only_and_versioned():
    result = evaluate_day_trade_spy_shadow_suite(
        _candles(),
        "CALL",
        feature_payload=_features(),
        option=_option(),
        trade_plan={"entry": 600.36, "stop": 599.90, "target": 601.00, "quantity": 1},
        captured_at=datetime(2026, 7, 29, 9, 50, tzinfo=ET),
    )

    assert result["schema_version"] == MODEL_VERSION
    assert result["shadow_only"] is True
    assert result["automatic_live_change_allowed"] is False
    assert set(result["tests"]) == {
        "accepted_break",
        "structural_room_execution",
        "opening_vs_later_entry",
        "congestion_reentry",
        "premise_reset_no_repair",
    }
    assert result["tests"]["structural_room_execution"]["verdict"] == "ADMIT"
    assert result["tests"]["premise_reset_no_repair"]["verdict"] == "TRACK"
    assert result["tests"]["premise_reset_no_repair"]["inputs"]["repair_add_allowed"] is False


def test_missing_historical_facts_are_unavailable_not_inferred():
    result = evaluate_day_trade_spy_shadow_suite(
        pd.DataFrame(),
        "PUT",
        captured_at=datetime(2026, 7, 29, 11, 0, tzinfo=ET),
        provenance="UNAVAILABLE",
    )

    assert result["provenance"] == "UNAVAILABLE"
    assert result["tests"]["accepted_break"]["verdict"] == "UNAVAILABLE"
    assert result["tests"]["structural_room_execution"]["verdict"] == "UNAVAILABLE"
    assert result["tests"]["premise_reset_no_repair"]["verdict"] == "UNAVAILABLE"


def test_wide_option_quote_is_rejected_only_by_shadow_evaluator():
    option = _option()
    option.update(bid=0.90, ask=1.10, mark=1.00)
    result = evaluate_day_trade_spy_shadow_suite(
        _candles(), "CALL", feature_payload=_features(), option=option
    )

    execution = result["tests"]["structural_room_execution"]
    assert execution["verdict"] == "REJECT"
    assert execution["reason"] == "option_not_executable"
    assert result["automatic_live_change_allowed"] is False


def test_trade_telemetry_copies_shadow_evaluation_id_without_control_fields():
    suite = evaluate_day_trade_spy_shadow_suite(
        _candles(), "CALL", feature_payload=_features(), option=_option()
    )
    position = SimpleNamespace(
        option_symbol=_option()["symbol"],
        direction="CALL",
        quantity=1,
        schwab_order_id="entry-1",
        schwab_fill_price=1.02,
        schwab_fill_timestamp="2026-07-29T09:50:00-04:00",
        option_entry=1.02,
        option_stop=0.90,
        option_initial_stop=0.90,
        option_high_since_entry=1.05,
        option_low_since_entry=1.00,
        option_trailing_high_bid=1.04,
        opened="2026-07-29T09:50:00-04:00",
        feature_payload='{"day_trade_spy_shadow_suite": ' + __import__("json").dumps(suite) + "}",
    )

    telemetry = build_option_management_cycle(
        position,
        spy_price=600.40,
        bid=1.03,
        ask=1.05,
        mark=1.04,
        observed_at=datetime(2026, 7, 29, 9, 51, tzinfo=ET),
    )

    assert telemetry["day_trade_spy_shadow_evaluation_id"] == suite["evaluation_id"]
    assert telemetry["day_trade_spy_shadow_suite"]["automatic_live_change_allowed"] is False
    assert "entry_allowed" not in telemetry


def test_actual_entry_quote_and_fill_are_persisted_without_control_output():
    suite = evaluate_day_trade_spy_shadow_suite(
        _candles(), "CALL", feature_payload=_features(), option=_option()
    )
    payload = attach_entry_quote_telemetry(
        {"day_trade_spy_shadow_suite": suite},
        quote_snapshot={
            "bid": 1.01,
            "ask": 1.03,
            "mark": 1.02,
            "last": 1.02,
            "quote_age_seconds": 0.4,
            "quote_spread_pct": 1.96,
            "quote_as_of": "2026-07-29T09:50:00-04:00",
            "quote_source": "schwab_direct",
        },
        submitted_limit_price=1.03,
        broker_fill_price=1.02,
        filled_via="limit",
    )
    decoded = __import__("json").loads(payload)

    quote = decoded["entry_option_quote_snapshot"]
    assert quote["broker_fill_price"] == 1.02
    assert quote["slippage_vs_limit_dollars"] == -0.01
    assert quote["provenance"] == "captured_live_pre_submit_quote_and_broker_fill"
    assert "entry_allowed" not in decoded
