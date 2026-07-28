import sqlite3

from engine.memory.service import Memory


def test_latency_projection_survives_transient_database_lock(tmp_path, monkeypatch):
    memory = Memory(db_path=tmp_path / "memory.db")
    projection_path = tmp_path / "latency.jsonl"

    def locked_record_event(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(memory, "record_event", locked_record_event)

    event = memory.record_latency({"cycle_total_ms": 500}, projection_path)

    assert event.category == "latency"
    assert projection_path.read_text(encoding="utf-8").strip() == '{"cycle_total_ms":500}'


def test_live_store_uses_wal_journaling(tmp_path):
    memory = Memory(db_path=tmp_path / "memory.db")

    memory.initialize_live_trade_store()

    with sqlite3.connect(memory.db_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"