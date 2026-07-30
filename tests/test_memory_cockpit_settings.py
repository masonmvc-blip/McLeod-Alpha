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
        def load_setting(self, projection_path, default=None):
            return default

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


def test_repeated_exit_click_reuses_active_command(monkeypatch, tmp_path):
    memory = Memory(db_path=tmp_path / "memory.sqlite")
    monkeypatch.setattr(cockpit, "CONTROL_COMMAND_FILE", tmp_path / "control_command.json")
    monkeypatch.setattr(cockpit, "get_memory", lambda: memory)

    first = cockpit.queue_exit_trade_command()
    second = cockpit.queue_exit_trade_command()

    assert second["id"] == first["id"]
    assert second["status"] == "PENDING"


def test_exit_endpoint_queues_exit_even_when_status_has_not_seen_open_position(monkeypatch):
    queued = []
    monkeypatch.setattr(cockpit, "parse_bot_status", lambda: {"bot_running": True, "mode": "LIVE TRADING", "has_open_position": False})
    monkeypatch.setattr(cockpit, "queue_exit_trade_command", lambda: queued.append(True) or {"id": 123})
    monkeypatch.setattr(cockpit, "flatten_all_spy_options", lambda *args, **kwargs: {
        "status": "flat", "initial_positions": {}, "submitted_orders": [],
    })
    monkeypatch.setattr(cockpit, "_get_broker_client", lambda: object())
    monkeypatch.setattr(cockpit, "toggle_entry_pause_command", lambda: (_ for _ in ()).throw(AssertionError("exit must not pause entries")))

    response = cockpit.app.test_client().post("/api/exit-trade")

    assert response.status_code == 200
    assert response.get_json()["command_id"] == 123
    assert queued == [True]


def test_entry_pause_endpoint_uses_dedicated_control(monkeypatch):
    monkeypatch.setattr(cockpit, "parse_bot_status", lambda: {"bot_running": True, "mode": "LIVE TRADING"})
    monkeypatch.setattr(cockpit, "toggle_entry_pause_command", lambda: {"paused": True})

    response = cockpit.app.test_client().post("/api/toggle-entry-pause")

    assert response.status_code == 200
    assert response.get_json()["entry_paused"] is True


def test_position_status_reports_local_exit_completion(monkeypatch, tmp_path):
    monkeypatch.setattr(cockpit, "PROJECT_ROOT", tmp_path)
    response = cockpit.app.test_client().get("/api/position-status")

    assert response.status_code == 200
    assert response.get_json()["has_open_position"] is False

    position_path = tmp_path / "data" / "open_position.json"
    position_path.parent.mkdir(parents=True)
    position_path.write_text('{"direction":"CALL","option_symbol":"SPY TEST"}', encoding="utf-8")
    response = cockpit.app.test_client().get("/api/position-status")

    assert response.get_json()["has_open_position"] is True
    assert response.get_json()["direction"] == "CALL"


def test_cockpit_has_market_open_paused_entry_prompt():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert 'Trading Paused' in source
    assert 'Do you want to enter trades?' in source
    assert 'maybePromptPausedEntriesAtMarketOpen(status)' in source
    assert "time >= '09:30' && time < '09:35'" in source
    assert "'/api/toggle-entry-pause'" in source


def test_cockpit_watches_for_confirmed_exit_completion():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert "function startExitCompletionWatch()" in source
    assert "'/api/position-status'" in source
    assert "setInterval(checkForCompletion, 250)" in source
    assert "await refreshStatus(true)" in source
    assert "updateTodaysTrades();" in source


def test_cockpit_uses_one_position_aware_trade_action_button():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert source.count('id="tradeActionBtn"') == 1
    assert 'id="exitTradeBtn"' not in source
    assert 'id="entryPauseBtn"' not in source
    assert "tradeActionButton.dataset.action = tradeActionIsExit ? 'exit' : 'entry-pause'" in source
    assert "const tradeActionIsExit = !!status.has_open_position" in source
    assert "function handleTradeAction()" in source
    assert ".trades-actions {" in source
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in source


def test_explicit_go_live_clears_operator_stop_marker():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert 'get_memory().clear_setting("bot_manual_stop_marker", BOT_MANUAL_STOP_MARKER_FILE)' in source
    assert 'env["MCLEOD_ALLOW_MARKET_HOURS_CHANGES"] = "1"' in source
