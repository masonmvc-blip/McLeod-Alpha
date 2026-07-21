from pathlib import Path

import cockpit


def test_stop_bot_persists_manual_stop_even_without_running_pid(monkeypatch, tmp_path):
    marker = tmp_path / "bot_manual_stop_marker.json"
    monkeypatch.setattr(cockpit, "BOT_MANUAL_STOP_MARKER_FILE", marker)
    monkeypatch.setattr(cockpit, "BOT_PID_FILE", tmp_path / "bot.pid")
    monkeypatch.setattr(cockpit, "get_bot_pid", lambda: None)
    monkeypatch.setattr(cockpit, "_is_bot_process_running", lambda: False)

    result = cockpit.stop_bot()

    assert result["status"] == "success"
    assert marker.exists()


def test_stack_start_respects_operator_stop_marker():
    source = (Path(cockpit.PROJECT_ROOT) / "ops" / "stack_start.sh").read_text(encoding="utf-8")

    assert 'if [[ -f "$MANUAL_STOP_MARKER" ]]; then' in source
    assert "operator stop is active" in source