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