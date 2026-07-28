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