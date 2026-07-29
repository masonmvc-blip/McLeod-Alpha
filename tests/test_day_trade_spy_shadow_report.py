import json
from pathlib import Path
import sqlite3

from reports.day_trade_spy_shadow_report import (
    build_day_trade_spy_shadow_report,
    write_day_trade_spy_shadow_report,
)
from scripts.backfill_day_trade_spy_shadow import backfill


def _root(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir()
    with sqlite3.connect(tmp_path / "data" / "mcleod_alpha.db") as connection:
        connection.execute(
            """
            CREATE TABLE trade_log (
                id INTEGER PRIMARY KEY,
                entry_time TEXT,
                exit_time TEXT,
                direction TEXT,
                exit_reason TEXT,
                option_symbol TEXT,
                option_entry REAL,
                option_exit REAL,
                option_pnl_dollars REAL,
                pnl REAL,
                broker_entry_order_id TEXT,
                broker_exit_order_id TEXT,
                mfe_pct REAL,
                mae_pct REAL,
                feature_payload TEXT,
                quantity INTEGER,
                stop REAL,
                target REAL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO trade_log VALUES (
                1, '2026-07-29T10:00:00-04:00', '2026-07-29T10:10:00-04:00',
                'CALL', 'TARGET', 'SPY-CALL', 1.00, 1.10, 10.0, 10.0,
                'entry-1', 'exit-1', 10.0, -2.0, '{}', 1, 599.5, 601.0
            )
            """
        )
    attribution = tmp_path / "reports" / "daily_loss_attribution"
    attribution.mkdir(parents=True)
    (attribution / "daily_loss_attribution_2026-07-29.json").write_text(
        json.dumps({"reconciliation": {"complete": True}}),
        encoding="utf-8",
    )
    return tmp_path


def test_historical_missing_candles_are_marked_unavailable(tmp_path):
    root = _root(tmp_path)
    report = build_day_trade_spy_shadow_report("2026-07-29", root=root)

    assert report["sample_size"] == 1
    assert report["trades"][0]["shadow_provenance"] == "UNAVAILABLE"
    assert report["trades"][0]["shadow_suite"]["tests"]["accepted_break"]["verdict"] == "UNAVAILABLE"
    assert report["shadow_only"] is True
    assert report["automatic_live_change_allowed"] is False


def test_writer_and_all_date_backfill_are_repeatable(tmp_path):
    root = _root(tmp_path)
    payload, json_path, csv_path, md_path = write_day_trade_spy_shadow_report(
        "2026-07-29", root=root
    )

    assert payload["promotion_gate"]["automatic_live_change_allowed"] is False
    assert json_path.exists() and csv_path.exists() and md_path.exists()
    assert backfill(root=root) == 1
    assert backfill(root=root) == 1
