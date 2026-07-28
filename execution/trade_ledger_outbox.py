"""Durable write-ahead queue for completed live-trade ledger records."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.memory import get_memory

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTBOX_PATH = PROJECT_ROOT / "data" / "reports" / "trade_ledger_outbox.jsonl"


def _key(trade: dict[str, Any]) -> str:
    return "|".join(str(trade.get(field) or "") for field in (
        "broker_entry_order_id", "broker_exit_order_id", "entry_time", "exit_time", "option_symbol",
    ))


def queue_completed_trade(trade: dict[str, Any]) -> str:
    """Persist a completed-trade fact before local position cleanup."""
    key = _key(trade)
    get_memory().append_report_line(
        OUTBOX_PATH,
        json.dumps({"event": "pending", "key": key, "queued_at": datetime.now(timezone.utc).isoformat(), "trade": trade}, default=str),
        "trade_ledger_outbox",
        source="live_engine",
        correlation_id=key,
    )
    return key


def _already_logged(connection: sqlite3.Connection, trade: dict[str, Any]) -> bool:
    entry_id = str(trade.get("broker_entry_order_id") or "")
    exit_id = str(trade.get("broker_exit_order_id") or "")
    if entry_id or exit_id:
        return connection.execute(
            "SELECT 1 FROM trade_log WHERE COALESCE(broker_entry_order_id, '') = ? AND COALESCE(broker_exit_order_id, '') = ? LIMIT 1",
            (entry_id, exit_id),
        ).fetchone() is not None
    return connection.execute(
        "SELECT 1 FROM trade_log WHERE entry_time = ? AND exit_time = ? AND option_symbol = ? LIMIT 1",
        (trade.get("entry_time"), trade.get("exit_time"), trade.get("option_symbol")),
    ).fetchone() is not None


def reconcile_completed_trade_outbox() -> int:
    """Idempotently replay queued confirmed closes into the canonical ledger."""
    if not OUTBOX_PATH.exists():
        return 0
    latest: dict[str, dict[str, Any]] = {}
    for line in OUTBOX_PATH.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = str(event.get("key") or "")
        if key:
            latest[key] = event
    memory = get_memory()
    memory.initialize_live_trade_store()
    inserted = 0
    for key, event in latest.items():
        if event.get("event") != "pending":
            continue
        trade = event.get("trade")
        if not isinstance(trade, dict):
            continue
        with sqlite3.connect(memory.db_path) as connection:
            if _already_logged(connection, trade):
                continue
        memory.record_trade(**trade)
        get_memory().append_report_line(
            OUTBOX_PATH,
            json.dumps({"event": "applied", "key": key, "applied_at": datetime.now(timezone.utc).isoformat()}),
            "trade_ledger_outbox",
            source="daily_trade_log_email",
            correlation_id=key,
        )
        inserted += 1
    return inserted