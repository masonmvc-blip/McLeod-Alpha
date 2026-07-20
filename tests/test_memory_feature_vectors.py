from __future__ import annotations

import json
import sqlite3

import pytest

from engine.memory import Memory
from execution import live_engine


def test_memory_records_versioned_feature_vector_once_per_correlation(tmp_path):
    memory = Memory(db_path=tmp_path / "memory.sqlite")
    payload = {"schema_version": "entry-feature-vector.v1", "direction": "CALL", "entry_score": 5}

    first = memory.record_feature_vector(payload, source="live_execution", correlation_id="entry-123")
    second = memory.record_feature_vector(payload, source="live_execution", correlation_id="entry-123")

    assert first.event_id == "feature-vector:entry-123"
    assert second.event_id == first.event_id
    with sqlite3.connect(memory.db_path) as connection:
        stored = connection.execute(
            "SELECT source, correlation_id, schema_version, payload FROM feature_vectors"
        ).fetchall()
        events = connection.execute(
            "SELECT event_id, category, event_type FROM memory_events"
        ).fetchall()
    assert stored == [("live_execution", "entry-123", "entry-feature-vector.v1", json.dumps({"direction": "CALL", "entry_score": 5}, separators=(",", ":")))]
    assert events == [("feature-vector:entry-123", "feature_vector", "feature_vector_recorded")]


def test_memory_rejects_invalid_feature_vector_payload(tmp_path):
    memory = Memory(db_path=tmp_path / "memory.sqlite")

    with pytest.raises(ValueError, match="valid JSON"):
        memory.record_feature_vector("not-json")


def test_live_adapter_routes_entry_feature_vector_through_memory(monkeypatch):
    recorded = []

    class _Memory:
        def record_feature_vector(self, payload, **kwargs):
            recorded.append((payload, kwargs))

    monkeypatch.setattr(live_engine, "get_memory", lambda: _Memory())

    live_engine._record_entry_feature_vector('{"entry_score": 5}', "entry-456")

    assert recorded == [
        ('{"entry_score": 5}', {"source": "live_execution", "correlation_id": "entry-456"})
    ]