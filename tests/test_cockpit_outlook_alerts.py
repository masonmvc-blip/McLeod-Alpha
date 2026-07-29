from types import SimpleNamespace

import cockpit


def test_bot_stop_email_uses_outlook(monkeypatch):
    calls = []
    monkeypatch.setenv("COCKPIT_ALERT_TRANSPORT", "outlook")
    monkeypatch.setenv("COCKPIT_ALERT_EMAIL", "operator@example.test")
    monkeypatch.setattr(
        cockpit.subprocess,
        "run",
        lambda args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(returncode=0, stderr="", stdout=""),
    )

    assert cockpit._send_bot_stop_email("Bot stopped", "Reason") is True
    assert calls[0][0][:2] == ["osascript", "-e"]
    assert 'tell application "Microsoft Outlook"' in calls[0][0][2]
    assert "operator@example.test" in calls[0][0][2]
