import json

import execution.live_engine as live_engine


def test_native_execution_alert_uses_nonblocking_afplay(monkeypatch, tmp_path):
    player = tmp_path / "afplay"
    profit_audio = tmp_path / "profit.mp3"
    loss_audio = tmp_path / "loss.mp3"
    for path in (player, profit_audio, loss_audio):
        path.touch()

    calls = []
    monkeypatch.setattr(live_engine, "NATIVE_AUDIO_PLAYER", player)
    monkeypatch.setattr(
        live_engine,
        "EXECUTION_AUDIO_PATHS",
        {"entry": profit_audio, "profit_exit": profit_audio, "loss_exit": loss_audio},
    )
    monkeypatch.setattr(live_engine.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))

    live_engine._play_execution_alert("entry")
    live_engine._play_execution_alert("exit", 25.0)
    live_engine._play_execution_alert("exit", -25.0)

    assert [call[0][0] for call in calls] == [
        [str(player), str(profit_audio)],
        [str(player), str(profit_audio)],
        [str(player), str(loss_audio)],
    ]
    assert all(call[1]["start_new_session"] is True for call in calls)


def test_native_execution_alert_never_raises_when_player_fails(monkeypatch, tmp_path):
    player = tmp_path / "afplay"
    audio = tmp_path / "entry.mp3"
    player.touch()
    audio.touch()
    monkeypatch.setattr(live_engine, "NATIVE_AUDIO_PLAYER", player)
    monkeypatch.setattr(live_engine, "EXECUTION_AUDIO_PATHS", {"entry": audio, "profit_exit": audio, "loss_exit": audio})
    monkeypatch.setattr(live_engine.subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("audio unavailable")))

    live_engine._play_execution_alert("entry")


def test_native_execution_alert_plays_each_broker_event_once(monkeypatch, tmp_path):
    player = tmp_path / "afplay"
    audio = tmp_path / "entry.mp3"
    state = tmp_path / "execution_audio_alerts.json"
    player.touch()
    audio.touch()
    calls = []
    monkeypatch.setattr(live_engine, "NATIVE_AUDIO_PLAYER", player)
    monkeypatch.setattr(
        live_engine,
        "EXECUTION_AUDIO_PATHS",
        {"entry": audio, "profit_exit": audio, "loss_exit": audio},
    )
    monkeypatch.setattr(live_engine, "EXECUTION_AUDIO_STATE_PATH", state)
    monkeypatch.setattr(live_engine.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))

    live_engine._play_execution_alert("exit", 25.0, event_id="exit:123")
    live_engine._play_execution_alert("exit", 25.0, event_id="exit:123")
    live_engine._play_execution_alert("exit", -25.0, event_id="exit:456")

    assert len(calls) == 2
    assert json.loads(state.read_text())["played_event_ids"] == ["exit:123", "exit:456"]


def test_native_execution_alert_is_silent_for_breakeven_exit(monkeypatch):
    calls = []
    monkeypatch.setattr(live_engine.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))

    live_engine._play_execution_alert("exit", 0.0, event_id="exit:breakeven")

    assert calls == []


def test_dashboard_polling_does_not_replay_execution_audio():
    cockpit_source = (
        live_engine.Path(__file__).resolve().parents[1] / "cockpit.py"
    ).read_text(encoding="utf-8")

    assert "playCashRegisterNoise" not in cockpit_source
    assert "playLossTrumpet" not in cockpit_source


def test_broker_reconciled_exit_uses_the_native_exit_alert():
    source = (live_engine.Path(__file__).resolve().parents[1] / "execution" / "live_engine.py").read_text(encoding="utf-8")
    reconciled_exit_index = source.index('source="LIVE_RECONCILED"')
    alert_index = source.index('_play_execution_alert(', reconciled_exit_index)

    assert alert_index > reconciled_exit_index
