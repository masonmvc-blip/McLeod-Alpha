import inspect
import json
import sqlite3
from pathlib import Path

import pandas as pd

import execution.trade_logger as trade_logger
import execution.daily_trade_log_email as daily_trade_log_email
import execution.paper_engine as paper_engine
import phase3_monitor


def _df(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])


def test_absorption_score_bullish_calculates_in_range():
    df = _df([
        [100.0, 101.0, 99.4, 99.6, 1000],
        [99.7, 100.4, 99.1, 99.5, 1300],
        [99.6, 100.0, 99.0, 99.55, 1500],
        [99.6, 100.1, 99.1, 99.58, 1700],
        [99.7, 100.2, 99.2, 99.62, 1800],
        [99.8, 100.3, 99.3, 99.70, 1900],
    ])
    score = phase3_monitor.absorption_score(df, direction="CALL")
    assert 0.0 <= float(score["score"]) <= 5.0
    assert "absorbed_pressure" in score["components"]


def test_absorption_score_not_in_confidence_signature():
    params = inspect.signature(phase3_monitor.confidence_score_engine).parameters
    assert "absorption" not in params
    assert "absorption_score" not in params


def test_trade_logger_persists_absorption_score(tmp_path, monkeypatch):
    test_db = tmp_path / "trade_log_test.db"
    monkeypatch.setattr(trade_logger, "DB", test_db)

    trade_logger.log_trade(
        entry_time="2026-07-16T10:00:00-04:00",
        exit_time="2026-07-16T10:05:00-04:00",
        direction="CALL",
        entry_price=750.0,
        exit_price=751.0,
        pnl=25.0,
        exit_reason="TEST",
        absorption_score=3.25,
    )

    with sqlite3.connect(test_db) as con:
        row = con.execute("SELECT absorption_score FROM trade_log ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    assert float(row[0]) == 3.25


def test_daily_trade_log_extracts_absorption_score():
    snap = {
        "absorption_score": 2.75,
        "absorption_score_call": {"score": 2.75},
        "absorption_score_put": {"score": 1.25},
    }
    assert daily_trade_log_email._extract_absorption_score(snap, "CALL") == 2.75
    assert daily_trade_log_email._extract_absorption_score(snap, "PUT") == 2.75


def test_entry_snapshot_includes_absorption_from_payload():
    payload = json.dumps({
        "trend_stage": {"stage": 2},
        "continuation_quality_score": 3.1,
        "momentum_acceleration_score": 3.6,
        "absorption_score": 2.2,
        "confidence_score": 2.8,
    })
    snapshot_text = paper_engine._extract_entry_diagnostic_snapshot(payload)
    assert json.loads(snapshot_text)["absorption_score"] == 2.2
