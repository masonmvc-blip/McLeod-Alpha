from __future__ import annotations

import sqlite3

from engine.memory import Memory
import execution.trade_ledger_outbox as outbox


def test_completed_trade_outbox_replays_once(monkeypatch, tmp_path):
    memory = Memory(db_path=tmp_path / "ledger.db")
    monkeypatch.setattr(outbox, "OUTBOX_PATH", tmp_path / "outbox.jsonl")
    monkeypatch.setattr(outbox, "get_memory", lambda: memory)
    trade = {
        "entry_time": "2026-07-23T10:00:00-04:00", "exit_time": "2026-07-23T10:05:00-04:00",
        "direction": "CALL", "entry_price": 600, "exit_price": 601, "pnl": 10,
        "exit_reason": "STOP", "option_symbol": "SPY  260723C00600000", "option_entry": 5,
        "option_exit": 5.1, "option_quantity": 1, "broker_entry_order_id": "entry-1", "broker_exit_order_id": "exit-1",
    }
    outbox.queue_completed_trade(trade)

    assert outbox.reconcile_completed_trade_outbox() == 1
    assert outbox.reconcile_completed_trade_outbox() == 0
    with sqlite3.connect(memory.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM trade_log").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM canonical_completed_trades").fetchone()[0] == 1


def test_completed_trade_reader_backfills_legacy_rows(tmp_path):
    memory = Memory(db_path=tmp_path / "ledger.db")
    memory.record_trade(
        entry_time="2026-07-23T10:00:00-04:00", exit_time="2026-07-23T10:05:00-04:00",
        direction="CALL", entry_price=600, exit_price=601, pnl=10, exit_reason="TARGET",
        option_symbol="SPY  260723C00600000", option_entry=5, option_exit=5.1, option_quantity=1,
        broker_entry_order_id="entry-2", broker_exit_order_id="exit-2",
    )

    trades = memory.load_completed_trades_for_date("2026-07-23")

    assert len(trades) == 1
    assert trades[0]["canonical_trade_id"].startswith("completed-trade:")
    assert trades[0]["schema_version"] == "canonical-completed-trade.v2"


def test_broker_correction_creates_new_canonical_version(tmp_path):
    memory = Memory(db_path=tmp_path / "ledger.db")
    trade = {
        "entry_time": "2026-07-23T10:00:00-04:00", "exit_time": "2026-07-23T10:05:00-04:00",
        "direction": "CALL", "entry_price": 600, "exit_price": 601, "pnl": 10,
        "exit_reason": "TARGET", "option_symbol": "SPY  260723C00600000", "option_entry": 5,
        "option_exit": 5.1, "option_quantity": 1, "broker_entry_order_id": "entry-3", "broker_exit_order_id": "exit-3",
        "feature_payload": '{"model_version":"model-7","market_regime":"strong_trend"}',
    }
    first = memory.upsert_completed_trade(trade, source="broker_reconciliation")
    repeated = memory.upsert_completed_trade(trade, source="broker_reconciliation")
    corrected = memory.upsert_completed_trade({**trade, "pnl": 9.75}, source="broker_reconciliation")

    assert first["canonical_trade_id"] == corrected["canonical_trade_id"]
    assert repeated["canonical_version"] == 1
    assert corrected["canonical_version"] == 2
    assert memory.load_completed_trades_for_date("2026-07-23")[0]["pnl"] == 9.75
    with sqlite3.connect(memory.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM canonical_completed_trade_versions").fetchone()[0] == 2


def test_reconciliation_metrics_detect_pending_and_unreconciled(tmp_path):
    memory = Memory(db_path=tmp_path / "data" / "ledger.db")
    broker_trade = {
        "entry_time": "2026-07-23T10:00:00-04:00", "exit_time": "2026-07-23T10:05:00-04:00",
        "direction": "CALL", "entry_price": 600, "exit_price": 601, "pnl": 10,
        "exit_reason": "TARGET", "option_symbol": "SPY  260723C00600000", "option_entry": 5,
        "option_exit": 5.1, "option_quantity": 1, "broker_entry_order_id": "entry-4", "broker_exit_order_id": "exit-4",
    }
    metrics = memory.load_trade_reconciliation_metrics("2026-07-23", [broker_trade])

    assert metrics["broker_trades_today"] == 1
    assert metrics["canonical_completed_trades"] == 0
    assert metrics["unreconciled_trades"] == 1