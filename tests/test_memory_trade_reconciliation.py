from __future__ import annotations

import ast
from datetime import datetime
import json
import sqlite3
from pathlib import Path

import cockpit
from engine.memory import Memory


def _broker_trade(entry_order_id="entry-1", exit_order_id="exit-1"):
    return {
        "entry_time": "2026-07-20T10:00:00-04:00",
        "exit_time": "2026-07-20T10:05:00-04:00",
        "direction": "CALL",
        "entry_price": 1.0,
        "exit_price": 1.2,
        "pnl": 20.0,
        "exit_reason": "4% TRAIL",
        "option_symbol": "SPY  260720C00600000",
        "option_entry": 1.0,
        "option_exit": 1.2,
        "option_quantity": 1,
        "broker_entry_order_id": entry_order_id,
        "broker_exit_order_id": exit_order_id,
    }


def test_memory_reconciles_broker_trade_once_and_records_correlated_event(tmp_path):
    memory = Memory(db_path=tmp_path / "memory.sqlite")
    trade = _broker_trade()

    assert memory.reconcile_broker_trades([trade]) == 1
    assert memory.reconcile_broker_trades([trade]) == 0

    with sqlite3.connect(memory.db_path) as connection:
        rows = connection.execute(
            "SELECT broker_entry_order_id, broker_exit_order_id FROM trade_log"
        ).fetchall()
        events = connection.execute(
            "SELECT event_type, source, correlation_id, payload FROM memory_events WHERE category = 'trade'"
        ).fetchall()
    assert rows == [("entry-1", "exit-1")]
    assert len(events) == 1
    assert events[0][:3] == ("broker_trade_reconciled", "broker_reconciliation", "broker-trade:entry-1:exit-1")
    assert json.loads(events[0][3])["schema_version"] == "broker-trade-reconciliation.v1"


def test_indicator_performance_summary_tracks_wins_losses_and_guidance():
    trades = [
        {
            "exit_time": "2026-07-20T10:05:00-04:00",
            "pnl": 20.0,
            "direction": "CALL",
            "option_symbol": "SPY  260720C00600000",
            "broker_entry_order_id": "indicator-entry-1",
            "broker_exit_order_id": "indicator-exit-1",
            "feature_payload": json.dumps({"entry_reasons": ["price_above_vwap"]}),
        },
        {
            "exit_time": "2026-07-20T10:10:00-04:00",
            "pnl": -10.0,
            "direction": "CALL",
            "option_symbol": "SPY  260720C00600000",
            "broker_entry_order_id": "indicator-entry-2",
            "broker_exit_order_id": "indicator-exit-2",
            "feature_payload": json.dumps({"entry_reasons": ["price_above_vwap"]}),
        },
    ]

    summary = cockpit._indicator_performance_summary(trades, minimum_sample_size=2)

    assert summary == [{
        "indicator": "price_above_vwap",
        "trades": 2,
        "wins": 1,
        "losses": 1,
        "breakeven": 0,
        "win_rate_pct": 50.0,
        "average_return": 5.0,
        "guidance": "Keep monitoring",
    }]


def test_indicator_performance_summary_ranks_more_wins_before_sample_size():
    trades = [
        {
            "exit_time": "2026-07-20T10:05:00-04:00",
            "pnl": 10.0,
            "direction": "CALL",
            "option_symbol": "SPY  260720C00600000",
            "broker_entry_order_id": "rank-entry-1",
            "broker_exit_order_id": "rank-exit-1",
            "feature_payload": json.dumps({"entry_reasons": ["two_wins"]}),
        },
        {
            "exit_time": "2026-07-20T10:10:00-04:00",
            "pnl": 10.0,
            "direction": "CALL",
            "option_symbol": "SPY  260720C00600000",
            "broker_entry_order_id": "rank-entry-2",
            "broker_exit_order_id": "rank-exit-2",
            "feature_payload": json.dumps({"entry_reasons": ["two_wins"]}),
        },
        {
            "exit_time": "2026-07-20T10:15:00-04:00",
            "pnl": 10.0,
            "direction": "CALL",
            "option_symbol": "SPY  260720C00600000",
            "broker_entry_order_id": "rank-entry-3",
            "broker_exit_order_id": "rank-exit-3",
            "feature_payload": json.dumps({"entry_reasons": ["one_win_many_trades"]}),
        },
        {
            "exit_time": "2026-07-20T10:20:00-04:00",
            "pnl": -10.0,
            "direction": "CALL",
            "option_symbol": "SPY  260720C00600000",
            "broker_entry_order_id": "rank-entry-4",
            "broker_exit_order_id": "rank-exit-4",
            "feature_payload": json.dumps({"entry_reasons": ["one_win_many_trades"]}),
        },
    ]

    summary = cockpit._indicator_performance_summary(trades, minimum_sample_size=2)

    assert [row["indicator"] for row in summary] == ["two_wins", "one_win_many_trades"]


def test_today_trades_endpoint_does_not_mutate_trade_ledger(monkeypatch, tmp_path):
    database_path = tmp_path / "data" / "mcleod_alpha.db"
    memory = Memory(db_path=database_path)
    today = datetime.now(cockpit.EASTERN_TZ).date().isoformat()
    memory.record_trade(
        entry_time=f"{today}T09:30:00-04:00",
        exit_time=f"{today}T09:35:00-04:00",
        direction="CALL",
        entry_price=1.0,
        exit_price=1.1,
        pnl=10.0,
        exit_reason="TARGET",
        option_symbol="SPY  260720C00600000",
        option_entry=1.0,
        option_exit=1.1,
        option_quantity=1,
        broker_entry_order_id="existing-entry",
        broker_exit_order_id="existing-exit",
    )

    monkeypatch.setattr(cockpit, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cockpit, "_broker_transaction_trades_for_date", lambda _: [_broker_trade("broker-entry", "broker-exit")])
    monkeypatch.setattr(cockpit, "_schwab_transaction_day_net_pnl", lambda _: None)
    monkeypatch.setattr(cockpit, "_broker_verified_trade_signatures", lambda _: None)
    monkeypatch.setattr(cockpit, "_load_latest_schwab_transaction_export", lambda: (None, None))
    monkeypatch.setattr(cockpit, "_log_daily_trades_chart_snapshot", lambda *args: None)
    monkeypatch.setattr(cockpit, "parse_bot_status", lambda: {"todays_pnl": 0.0})

    with sqlite3.connect(database_path) as connection:
        before_count = connection.execute("SELECT COUNT(*) FROM trade_log").fetchone()[0]
    response = cockpit.app.test_client().get("/api/today-trades")
    with sqlite3.connect(database_path) as connection:
        after_count = connection.execute("SELECT COUNT(*) FROM trade_log").fetchone()[0]
        broker_rows = connection.execute(
            "SELECT COUNT(*) FROM trade_log WHERE broker_entry_order_id = 'broker-entry'"
        ).fetchone()[0]

    assert response.status_code == 200
    assert response.get_json()["trades"]
    assert before_count == after_count == 1
    assert broker_rows == 0


def test_today_trades_uses_broker_net_status_total_including_commissions(monkeypatch, tmp_path):
    database_path = tmp_path / "data" / "mcleod_alpha.db"
    memory = Memory(db_path=database_path)
    today = datetime.now(cockpit.EASTERN_TZ).date().isoformat()
    memory.record_trade(
        entry_time=f"{today}T09:30:00-04:00",
        exit_time=f"{today}T09:35:00-04:00",
        direction="CALL",
        entry_price=1.0,
        exit_price=1.1,
        pnl=-644.55,
        exit_reason="TARGET",
        option_symbol="SPY  260720C00600000",
        option_entry=1.0,
        option_exit=1.1,
        option_quantity=1,
        broker_entry_order_id="commission-entry",
        broker_exit_order_id="commission-exit",
    )

    monkeypatch.setattr(cockpit, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cockpit, "_broker_transaction_trades_for_date", lambda _: [])
    monkeypatch.setattr(cockpit, "_schwab_transaction_day_net_pnl", lambda _: -644.55)
    monkeypatch.setattr(cockpit, "_broker_verified_trade_signatures", lambda _: None)
    monkeypatch.setattr(cockpit, "_load_latest_schwab_transaction_export", lambda: (None, None))
    monkeypatch.setattr(cockpit, "_log_daily_trades_chart_snapshot", lambda *args: None)
    monkeypatch.setattr(cockpit, "parse_bot_status", lambda: {"todays_pnl": -644.62})

    response = cockpit.app.test_client().get("/api/today-trades")

    assert response.status_code == 200
    assert response.get_json()["summary"]["total_pnl"] == -644.62


def test_today_trades_preserves_entry_diagnostics_for_broker_canonical_rows(monkeypatch, tmp_path):
    database_path = tmp_path / "data" / "mcleod_alpha.db"
    memory = Memory(db_path=database_path)
    today = datetime.now(cockpit.EASTERN_TZ).date().isoformat()
    snapshot = {
        "checklist": {"passed": 5, "total": 5},
        "trend_stage": {"stage": 3},
        "continuation_quality_score": 4.2,
        "momentum_acceleration_score": 3.7,
        "absorption_score": 2.9,
        "confidence_score": 88.0,
    }
    memory.record_trade(
        entry_time=f"{today}T09:30:00-04:00",
        exit_time=f"{today}T09:35:00-04:00",
        direction="CALL",
        entry_price=1.0,
        exit_price=1.2,
        pnl=20.0,
        exit_reason="TARGET",
        option_symbol="SPY  260720C00600000",
        option_entry=1.0,
        option_exit=1.2,
        option_quantity=1,
        broker_entry_order_id="broker-entry",
        broker_exit_order_id="broker-exit",
        entry_diagnostic_snapshot=json.dumps(snapshot),
    )

    monkeypatch.setattr(cockpit, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cockpit, "_broker_transaction_trades_for_date", lambda _: [_broker_trade("broker-entry", "broker-exit")])
    monkeypatch.setattr(cockpit, "_schwab_transaction_day_net_pnl", lambda _: None)
    monkeypatch.setattr(cockpit, "_broker_verified_trade_signatures", lambda _: None)
    monkeypatch.setattr(cockpit, "_load_latest_schwab_transaction_export", lambda: (None, None))
    monkeypatch.setattr(cockpit, "_log_daily_trades_chart_snapshot", lambda *args: None)
    monkeypatch.setattr(cockpit, "parse_bot_status", lambda: {"todays_pnl": 0.0})

    response = cockpit.app.test_client().get("/api/today-trades")

    assert response.status_code == 200
    trade = response.get_json()["trades"][0]
    assert trade["indicator_count"] == 5
    assert trade["indicator_total"] == 5
    assert trade["trend_stage"] == 3
    assert trade["continuation_quality_score"] == 4.2
    assert trade["momentum_acceleration_score"] == 3.7
    assert trade["absorption_score"] == 2.9
    assert trade["confidence_score"] == 88.0


def test_cockpit_has_no_direct_trade_log_mutation():
    tree = ast.parse(Path("cockpit.py").read_text(encoding="utf-8"))
    forbidden_prefixes = ("INSERT INTO TRADE_LOG", "UPDATE TRADE_LOG", "DELETE FROM TRADE_LOG", "REPLACE INTO TRADE_LOG")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"execute", "executemany", "executescript"} or not node.args:
            continue
        statement = node.args[0]
        if not isinstance(statement, ast.Constant) or not isinstance(statement.value, str):
            continue
        normalized = " ".join(statement.value.upper().split())
        assert not normalized.startswith(forbidden_prefixes), f"cockpit.py:{node.lineno} mutates trade_log directly"