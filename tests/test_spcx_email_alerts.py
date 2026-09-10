import json
from types import SimpleNamespace

from ops import spcx_email_alerts


def test_outlook_sender_uses_supported_recipient_shape(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["script"] = args[2]
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(spcx_email_alerts.subprocess, "run", fake_run)
    assert spcx_email_alerts._send_outlook(
        "owner@example.com", "SPCX test", "Delivery check"
    )
    assert 'email address:{address:"owner@example.com"}' in captured["script"]
    assert "visible:false" not in captured["script"]


def test_cash_alert_sends_only_once_per_session(tmp_path, monkeypatch):
    state_path = tmp_path / "email_alert_state.json"
    deliveries = []
    monkeypatch.setattr(spcx_email_alerts, "STATE_PATH", state_path)
    monkeypatch.setattr(spcx_email_alerts, "_recipient", lambda: "owner@example.com")
    monkeypatch.setattr(spcx_email_alerts, "_transport", lambda: "outlook")
    monkeypatch.setattr(
        spcx_email_alerts,
        "_send_outlook",
        lambda to_email, subject, body: deliveries.append((to_email, subject, body)) or True,
    )

    assert spcx_email_alerts.send_insufficient_balance_alert_once(
        "2026-09-10", available="135.65", required="153.98", margin_enabled=True
    )
    assert not spcx_email_alerts.send_insufficient_balance_alert_once(
        "2026-09-10", available="135.65", required="153.98", margin_enabled=True
    )
    assert len(deliveries) == 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["sent"] is True


def test_failed_cash_alert_can_retry(tmp_path, monkeypatch):
    state_path = tmp_path / "email_alert_state.json"
    attempts = []
    monkeypatch.setattr(spcx_email_alerts, "STATE_PATH", state_path)
    monkeypatch.setattr(spcx_email_alerts, "_recipient", lambda: "owner@example.com")
    monkeypatch.setattr(spcx_email_alerts, "_transport", lambda: "outlook")
    monkeypatch.setattr(
        spcx_email_alerts,
        "_send_outlook",
        lambda *_args: attempts.append(1) and False,
    )

    assert not spcx_email_alerts.send_insufficient_balance_alert_once(
        "2026-09-10", available="135.65", required="153.98", margin_enabled=True
    )
    assert not spcx_email_alerts.send_insufficient_balance_alert_once(
        "2026-09-10", available="135.65", required="153.98", margin_enabled=True
    )
    assert len(attempts) == 2
