import json
from datetime import datetime
from zoneinfo import ZoneInfo

import reports.scheduler_health as health


def test_scheduler_health_marks_late_unsent_email_as_missed(tmp_path, monkeypatch):
    state_path = tmp_path / "email_state.json"
    state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(health, "EMAIL_STATE_PATH", state_path)
    monkeypatch.setattr(health, "_email_target_time", lambda: datetime.strptime("15:01", "%H:%M").time())

    json_path, html_path = health.build_scheduler_health_dashboard(
        datetime(2026, 7, 21, 15, 5, tzinfo=ZoneInfo("America/Chicago")), tmp_path
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["tasks"][0]["task"] == "Daily Trade Email"
    assert payload["tasks"][0]["status"] == "missed"
    assert payload["health_summary"] == "attention_required"
    assert "Scheduler Health" in html_path.read_text(encoding="utf-8")


def test_missed_email_watchdog_sends_one_alert_after_fifteen_minutes(tmp_path, monkeypatch):
    state_path = tmp_path / "email_state.json"
    watchdog_state_path = tmp_path / "watchdog_state.json"
    state_path.write_text("{}", encoding="utf-8")
    alerts = []

    monkeypatch.setattr(health, "EMAIL_STATE_PATH", state_path)
    monkeypatch.setattr(health, "WATCHDOG_STATE_PATH", watchdog_state_path)
    monkeypatch.setattr(health, "_email_target_time", lambda: datetime.strptime("15:01", "%H:%M").time())
    monkeypatch.setattr(
        "execution.sms_alerts.send_emergency_alert",
        lambda title, details: alerts.append((title, details)) or True,
    )

    now_ct = datetime(2026, 7, 21, 15, 16, tzinfo=ZoneInfo("America/Chicago"))
    health.maybe_generate_scheduler_health_dashboard(now_ct)
    health.maybe_generate_scheduler_health_dashboard(now_ct.replace(minute=17))

    assert len(alerts) == 1
    assert alerts[0][0] == "DAILY TRADE EMAIL MISSED"
    state = json.loads(watchdog_state_path.read_text(encoding="utf-8"))
    assert state["alert_date"] == "2026-07-21"
    assert state["alert_delivered"] is True