from __future__ import annotations

import ast
import csv
import json
import sqlite3
from pathlib import Path

from engine.memory import Memory
from engine import weight_optimizer


def test_weight_optimizer_preserves_csv_and_markdown_projections_through_memory(tmp_path, monkeypatch):
    predictions_path = tmp_path / "model_predictions_history.csv"
    factor_history_path = tmp_path / "factor_performance_history.csv"
    report_path = tmp_path / "weekly_model_improvement.md"
    memory = Memory(db_path=tmp_path / "memory.sqlite")
    monkeypatch.setattr(weight_optimizer, "PREDICTIONS_HISTORY_CSV", predictions_path)
    monkeypatch.setattr(weight_optimizer, "FACTOR_PERF_HISTORY_CSV", factor_history_path)
    monkeypatch.setattr(weight_optimizer, "WEEKLY_REPORT", report_path)
    optimizer = weight_optimizer.WeightOptimizer(memory=memory)

    memory.write_optimization_csv(
        predictions_path,
        ["prediction_week", "symbol", "resolved_1w"],
        [{"prediction_week": "2026-W29", "symbol": "XYZ", "resolved_1w": "1"}],
        "prediction_history_fixture",
        source="test",
    )
    assert optimizer._load_history() == [{"prediction_week": "2026-W29", "symbol": "XYZ", "resolved_1w": "1"}]
    optimizer._append_factor_history([{"evaluation_week": "2026-W29", "factor": "component_quality", "evidence": "first"}])
    optimizer._append_factor_history([{"evaluation_week": "2026-W30", "factor": "component_growth", "evidence": "second"}])
    optimizer._write_report({"status": "insufficient_history", "reason": "Need more data."})

    with factor_history_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
        assert handle.seek(0) == 0
        assert next(csv.reader(handle)) == weight_optimizer.FACTOR_HISTORY_FIELDS
    assert [(row["evaluation_week"], row["factor"], row["evidence"]) for row in rows] == [
        ("2026-W29", "component_quality", "first"),
        ("2026-W30", "component_growth", "second"),
    ]
    report_text = report_path.read_text(encoding="utf-8")
    assert report_text.startswith("# Weekly Model Improvement\n\nGenerated: ")
    assert "- Status: insufficient_history" in report_text
    assert "- Reason: Need more data." in report_text

    with sqlite3.connect(memory.db_path) as connection:
        events = connection.execute("SELECT payload FROM memory_events WHERE category = 'optimization'").fetchall()
    payloads = [json.loads(row[0]) for row in events]
    assert [payload["artifact_type"] for payload in payloads] == [
        "prediction_history_fixture",
        "factor_performance_history",
        "factor_performance_history",
        "weekly_model_improvement",
    ]
    assert {payload["schema_version"] for payload in payloads} == {"optimization-artifact.v1"}


def test_weight_optimizer_has_no_direct_persistence_calls():
    tree = ast.parse(Path("engine/weight_optimizer.py").read_text(encoding="utf-8"))
    forbidden_attributes = {"write_text", "write_bytes", "read_text", "read_bytes", "open", "mkdir", "replace", "to_csv", "to_json"}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_attributes:
            raise AssertionError(f"engine/weight_optimizer.py:{node.lineno} directly calls {node.func.attr}")
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            raise AssertionError(f"engine/weight_optimizer.py:{node.lineno} directly opens a file")