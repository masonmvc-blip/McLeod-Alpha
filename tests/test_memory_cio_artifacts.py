from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path

from engine.memory import Memory


def test_memory_writes_cio_experiment_artifacts_and_events(tmp_path):
    memory = Memory(db_path=tmp_path / "memory.sqlite")
    artifact_path = tmp_path / "artifacts" / "cio" / "evidence.jsonl"

    memory.write_experiment_text(artifact_path, '{"seed":true}\n', "cio_evidence_ledger", source="cio_evidence_ledger")
    memory.append_experiment_line(artifact_path, json.dumps({"evidence_id": "e-1"}), "cio_evidence", source="cio_evidence_ledger", correlation_id="e-1")

    assert memory.read_experiment_text(artifact_path, encoding="utf-8") == '{"seed":true}\n{"evidence_id": "e-1"}\n'
    with sqlite3.connect(memory.db_path) as connection:
        events = connection.execute("SELECT payload, correlation_id FROM memory_events WHERE category = 'experiment'").fetchall()
    assert len(events) == 2
    assert {json.loads(payload)["schema_version"] for payload, _ in events} == {"experiment-artifact.v1"}
    assert {correlation_id for _, correlation_id in events} == {None, "e-1"}


def test_cio_artifact_producers_have_no_direct_persistence_calls():
    producer_paths = (
        "engine/cio/evidence_ledger.py",
        "engine/cio/decision_journal.py",
        "engine/cio/evidence_replay.py",
    )
    forbidden_attributes = {"write_text", "write_bytes", "read_text", "read_bytes", "open", "mkdir", "replace"}

    for relative_path in producer_paths:
        tree = ast.parse(Path(relative_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_attributes:
                raise AssertionError(f"{relative_path}:{node.lineno} directly calls {node.func.attr}")
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "sqlite3"
                and node.func.attr == "connect"
            ):
                raise AssertionError(f"{relative_path}:{node.lineno} directly connects to SQLite")