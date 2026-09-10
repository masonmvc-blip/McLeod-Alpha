import json

from ops import spcx_email_alerts


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

    assert spcx_email_alerts.send_insufficient_cash_alert_once(
        "2026-09-10", available="135.65", required="153.98"
    )
    assert not spcx_email_alerts.send_insufficient_cash_alert_once(
        "2026-09-10", available="135.65", required="153.98"
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

    assert not spcx_email_alerts.send_insufficient_cash_alert_once(
        "2026-09-10", available="135.65", required="153.98"
    )
    assert not spcx_email_alerts.send_insufficient_cash_alert_once(
        "2026-09-10", available="135.65", required="153.98"
    )
    assert len(attempts) == 2
