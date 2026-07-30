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


def test_outlook_sms_falls_back_to_authenticated_smtp(monkeypatch):
    monkeypatch.setenv("ENABLE_TRADE_SMS_ALERTS", "true")
    monkeypatch.setenv("TRADE_ALERT_TRANSPORT", "outlook_sms")
    monkeypatch.setenv("TRADE_ALERT_TO_GATEWAY", "123@example.test")
    monkeypatch.setattr(alerts, "_send_via_outlook_sms", lambda _body: False)
    monkeypatch.setattr(alerts, "_send_via_email_sms", lambda _body: True)

    assert alerts._send_sms("critical alert") is True


def test_email_gateway_accepts_unified_review_credentials(monkeypatch):
    for key in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EMAIL_ADDRESS", "operator@gmail.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "app password")
    monkeypatch.setenv("TRADE_ALERT_TO_GATEWAY", "123@example.test")

    cfg = alerts._email_cfg()

    assert cfg is not None
    assert cfg["host"] == "smtp.gmail.com"
    assert cfg["user"] == "operator@gmail.com"
    assert cfg["password"] == "apppassword"
