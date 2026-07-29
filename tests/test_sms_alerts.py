from types import SimpleNamespace

import execution.sms_alerts as alerts


def test_outlook_sms_transport_routes_to_microsoft_outlook(monkeypatch):
    calls = []
    monkeypatch.setenv("ENABLE_TRADE_SMS_ALERTS", "true")
    monkeypatch.setenv("TRADE_ALERT_TRANSPORT", "outlook_sms")
    monkeypatch.setenv("TRADE_ALERT_TO_GATEWAY", "123@example.test")
    monkeypatch.setattr(
        alerts.subprocess,
        "run",
        lambda args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(returncode=0, stderr="", stdout=""),
    )

    assert alerts._send_sms("test alert") is True
    assert calls[0][0][:2] == ["osascript", "-e"]
    assert 'tell application "Microsoft Outlook"' in calls[0][0][2]
    assert "123@example.test" in calls[0][0][2]


def test_outlook_sms_requires_gateway(monkeypatch):
    monkeypatch.setenv("ENABLE_TRADE_SMS_ALERTS", "true")
    monkeypatch.setenv("TRADE_ALERT_TRANSPORT", "outlook_sms")
    monkeypatch.delenv("TRADE_ALERT_TO_GATEWAY", raising=False)

    assert alerts._send_sms("test alert") is False
