import csv
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import cockpit
import pandas as pd
import phase3_monitor


ET = ZoneInfo("America/New_York")


def _write_candles(path):
    rows = [
        {"datetime": "2026-07-20T14:14:00+00:00", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        {"datetime": "2026-07-20T14:15:00+00:00", "open": 100, "high": 102, "low": 100, "close": 101, "volume": 1100},
        {"datetime": "2026-07-20T14:16:00+00:00", "open": 101, "high": 103, "low": 101, "close": 102, "volume": 1200},
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_indicator_snapshot_excludes_forming_minute(tmp_path):
    history_path = tmp_path / "spy_1min_history.csv"
    _write_candles(history_path)

    during_current_minute = cockpit._compute_candle_indicator_snapshot(
        now_et=datetime(2026, 7, 20, 10, 16, 30, tzinfo=ET),
        history_path=history_path,
    )
    after_current_minute_closes = cockpit._compute_candle_indicator_snapshot(
        now_et=datetime(2026, 7, 20, 10, 17, 1, tzinfo=ET),
        history_path=history_path,
    )

    assert during_current_minute["timestamp"].startswith("2026-07-20T10:15:00")
    assert after_current_minute_closes["timestamp"].startswith("2026-07-20T10:16:00")


def test_indicator_snapshot_uses_strategy_score_for_closed_candles(tmp_path):
    history_path = tmp_path / "spy_1min_history.csv"
    _write_candles(history_path)
    now = datetime(2026, 7, 20, 10, 17, 1, tzinfo=ET)

    snapshot = cockpit._compute_candle_indicator_snapshot(now_et=now, history_path=history_path)
    frame = pd.read_csv(history_path)
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    expected = phase3_monitor.score_closed_candle_frame(frame)

    assert snapshot["call_passed"] == max(0, min(5, int(expected["call_score"])))
    assert snapshot["put_passed"] == max(0, min(5, int(expected["put_score"])))
    assert snapshot["regime"] == expected["regime"]


def test_qualifying_side_shows_matching_closed_candle_no_entry_reason(tmp_path):
    audit_path = tmp_path / "decision_audit_history.jsonl"
    snapshot = {"timestamp": "2026-07-20T10:16:00-04:00"}
    event = {
        "event_type": "entry_evaluation",
        "candle_time": "2026-07-20T14:16:00+00:00",
        "entry_opened": False,
        "regime": "BEAR_TREND",
        "call_score": 5,
        "put_score": 5,
        "entry_decision_reason": "no_entry_signal",
    }
    audit_path.write_text(json.dumps(event) + "\n", encoding="utf-8")

    reasons = cockpit._indicator_no_entry_reasons(snapshot, audit_path=audit_path)

    assert reasons["CALL"] == "Regime is Bear Trend; CALL requires BULL TREND"
    assert reasons["PUT"] == "no entry signal"


def test_active_stop_reason_uses_the_actual_stop_price():
    assert cockpit._active_stop_category(5.00, stop_price=4.75) == "Stop"
    assert cockpit._active_stop_category(5.00, stop_price=5.27) == "6% Trail"


def test_option_label_includes_strike_for_calls_and_puts():
    assert cockpit._position_label_from_option_symbol("SPY   260720C00755000") == "$755 Call"
    assert cockpit._position_label_from_option_symbol("SPY   260720P00752250") == "$752.25 Put"