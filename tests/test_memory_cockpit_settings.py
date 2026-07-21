from __future__ import annotations

import sqlite3

import cockpit

from engine.memory import Memory


def test_memory_settings_are_atomically_projected_and_evented(tmp_path):
    projection = tmp_path / "control_command.json"
    memory = Memory(db_path=tmp_path / "memory.sqlite")

    saved = memory.save_setting("control_command", {"action": "EXIT_TRADE"}, projection)

    assert memory.load_setting(projection) == {"action": "EXIT_TRADE"}
    assert not projection.with_suffix(".json.tmp").exists()
    with sqlite3.connect(memory.db_path) as connection:
        events = connection.execute(
            "SELECT category, event_type, correlation_id FROM memory_events"
        ).fetchall()
    assert saved.category == "setting"
    assert events == [("setting", "setting_saved", "control_command")]


def test_memory_clear_setting_removes_projection_and_records_event(tmp_path):
    projection = tmp_path / "bot_manual_stop_marker.json"
    memory = Memory(db_path=tmp_path / "memory.sqlite")
    memory.save_setting("bot_manual_stop_marker", {"pid": 42}, projection)

    memory.clear_setting("bot_manual_stop_marker", projection)

    assert not projection.exists()
    with sqlite3.connect(memory.db_path) as connection:
        events = connection.execute(
            "SELECT event_type FROM memory_events ORDER BY occurred_at"
        ).fetchall()
    assert events == [("setting_saved",), ("setting_cleared",)]


def test_cockpit_operator_actions_delegate_to_memory(monkeypatch, tmp_path):
    calls = []

    class _Memory:
        def save_setting(self, name, value, projection_path=None):
            calls.append(("save", name, value, projection_path))

        def setting_projection_revision(self, projection_path):
            return 1

        def clear_setting(self, name, projection_path=None):
            calls.append(("clear", name, projection_path))

    memory = _Memory()
    monkeypatch.setattr(cockpit, "get_memory", lambda: memory)
    monkeypatch.setattr(cockpit, "PARITY_BASELINE_FILE", tmp_path / "parity_baseline.json")
    monkeypatch.setattr(cockpit, "CONTROL_COMMAND_FILE", tmp_path / "control_command.json")

    cockpit._save_parity_baseline({"cockpit_sha256": "abc"})
    command = cockpit.queue_exit_trade_command()

    assert calls[0][:3] == ("save", "parity_baseline", {"cockpit_sha256": "abc"})
    assert calls[1][0:2] == ("save", "control_command")
    assert calls[1][2] == command


def test_entry_pause_toggle_is_persisted(monkeypatch, tmp_path):
    memory = Memory(db_path=tmp_path / "memory.sqlite")
    monkeypatch.setattr(cockpit, "ENTRY_PAUSE_FILE", tmp_path / "entry_pause.json")
    monkeypatch.setattr(cockpit, "get_memory", lambda: memory)

    assert cockpit.toggle_entry_pause_command()["paused"] is True
    assert cockpit.toggle_entry_pause_command()["paused"] is False


def test_explicit_go_live_clears_operator_stop_marker():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert 'get_memory().clear_setting("bot_manual_stop_marker", BOT_MANUAL_STOP_MARKER_FILE)' in source
    assert 'env["MCLEOD_ALLOW_MARKET_HOURS_CHANGES"] = "1"' in source