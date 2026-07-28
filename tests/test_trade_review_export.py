from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone

from reports.trade_review_export import generate_trade_review_package


def _write_export(root):
    path = root / "data" / "reports" / "trade_logs" / "daily_trade_review_data_2026-07-23.json"
    path.parent.mkdir(parents=True)
    entry = datetime(2026, 7, 23, 14, 0, tzinfo=timezone.utc)
    path.write_text(json.dumps({"trades": [{
        "trade_id": "completed-trade:test-1", "canonical_trade_id": "completed-trade:test-1", "canonical_version": 1, "direction": "CALL", "option_symbol": "SPY  260723C00600000",
        "entry_time": entry.isoformat(), "exit_time": (entry + timedelta(minutes=8)).isoformat(),
        "option_entry_price": 5.0, "option_exit_price": 4.8, "option_quantity": 1,
        "dollar_pnl": -20.0, "percent_pnl": -4.0, "mae_pct": 4.5,
        "profit_left_on_table_dollars": 12.0, "peak_capture_pct": 20.0,
        "entry_score": 72, "positives": ["trend"], "penalties": ["late_alignment"],
        "entry_features": {"ema_10": 600.2, "rsi": 58}, "exit_reason": "STOP",
    }]}), encoding="utf-8")
    return path


def _write_candles(root):
    path = root / "data" / "spy_1min_history.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 7, 23, 13, 0, tzinfo=timezone.utc)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["datetime", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for index in range(120):
            price = 600 + index * .02
            writer.writerow({"datetime": (start + timedelta(minutes=index)).isoformat(), "open": price, "high": price + .05, "low": price - .05, "close": price + .01, "volume": 1000})


def test_trade_review_export_creates_chatgpt_ready_package(tmp_path):
    export_path = _write_export(tmp_path)
    _write_candles(tmp_path)

    output = generate_trade_review_package(tmp_path, "2026-07-23", export_path)

    assert (output / "SessionSummary.md").exists()
    assert (output / "SessionSummary.json").exists()
    assert (output / "ReviewQuestions.md").exists()
    assert (output / "Trade01.json").exists()
    assert (output / "Trade01_1m.png").exists()
    trade = json.loads((output / "Trade01.json").read_text(encoding="utf-8"))
    assert trade["bot_state_at_entry"]["all_persisted_feature_values"]["rsi"] == 58
    questions = (output / "ReviewQuestions.md").read_text(encoding="utf-8")
    assert "Should this trade have been filtered out" in questions