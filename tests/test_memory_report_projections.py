from __future__ import annotations

import ast
import csv
import json
import sqlite3
from pathlib import Path

from engine.memory import Memory


def test_memory_writes_versioned_report_projections_and_events(tmp_path):
    memory = Memory(db_path=tmp_path / "memory.sqlite")
    text_path = tmp_path / "report.md"
    json_path = tmp_path / "report.json"
    csv_path = tmp_path / "report.csv"
    log_path = tmp_path / "report.jsonl"

    memory.write_report_text(text_path, "# Report\n", "daily_summary", correlation_id="report-1")
    memory.write_report_json(json_path, {"value": 1}, "daily_summary", correlation_id="report-1")
    memory.write_report_csv(csv_path, ["date", "pnl"], [{"date": "2026-07-20", "pnl": 5}], "daily_summary", correlation_id="report-1")
    memory.append_report_line(log_path, json.dumps({"status": "created"}), "daily_summary", correlation_id="report-1")

    assert text_path.read_text(encoding="utf-8") == "# Report\n"
    assert json.loads(json_path.read_text(encoding="utf-8")) == {"value": 1}
    assert list(csv.DictReader(csv_path.open(encoding="utf-8"))) == [{"date": "2026-07-20", "pnl": "5"}]
    assert log_path.read_text(encoding="utf-8") == '{"status": "created"}\n'
    with sqlite3.connect(memory.db_path) as connection:
        events = connection.execute("SELECT payload FROM memory_events WHERE category = 'report'").fetchall()
    assert len(events) == 4
    assert all(json.loads(row[0])["schema_version"] == "report-artifact.v1" for row in events)


def test_report_producers_have_no_direct_persistence_calls():
    producer_paths = (
        "daily_report.py",
        "execution/daily_trade_log_email.py",
        "execution/opportunity_logger.py",
        "reports/broker_only_daily_pnl_report.py",
        "reports/daily_opportunity_review.py",
        "reports/daily_strategy_effectiveness.py",
        "cio_email/morning_report.py",
        "scripts/run_mcleod_report.py",
        "scripts/weekly_latency_insights.py",
        "scripts/send_daily_latency_email.py",
    )
    forbidden_calls = {"write_text", "write_bytes", "to_csv", "to_json", "FileHandler"}

    for relative_path in producer_paths:
        tree = ast.parse(Path(relative_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_calls:
                raise AssertionError(f"{relative_path}:{node.lineno} directly calls {node.func.attr}")
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "sqlite3"
                and node.func.attr == "connect"
            ):
                raise AssertionError(f"{relative_path}:{node.lineno} directly connects to SQLite")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "open":
                mode = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else "r"
                if any(flag in str(mode) for flag in "wax+"):
                    raise AssertionError(f"{relative_path}:{node.lineno} directly opens a writable file")