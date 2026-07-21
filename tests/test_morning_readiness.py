import json
from datetime import datetime
from zoneinfo import ZoneInfo

import reports.morning_readiness as readiness


def _flat_broker():
    return [], [], 200, None


def _configure_channels(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "password")
    monkeypatch.setenv("ENABLE_TRADE_SMS_ALERTS", "true")
    monkeypatch.setenv("TRADE_ALERT_TRANSPORT", "email_sms")
    monkeypatch.setenv("TRADE_ALERT_TO_GATEWAY", "123@example.test")


def test_readiness_pauses_entries_for_stale_local_position(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    scheduler = reports_dir / "scheduler_health.json"
    scheduler.write_text(json.dumps({"trade_date": "2026-07-22", "tasks": [{"task": "Daily Trade Email", "status": "scheduled"}]}), encoding="utf-8")
    local_position = tmp_path / "open_position.json"
    local_position.write_text(json.dumps({"option_symbol": "SPY_TEST"}), encoding="utf-8")
    pause_path = tmp_path / "entry_pause.json"
    monkeypatch.setattr(readiness, "ENTRY_PAUSE_PATH", pause_path)
    monkeypatch.setattr(readiness, "_cockpit_status", lambda: {"bot_running_effective": True})
    _configure_channels(monkeypatch)

    result = readiness.build_morning_readiness(datetime(2026, 7, 22, 9, 0, tzinfo=ZoneInfo("America/New_York")), _flat_broker, reports_dir=reports_dir, db_path=tmp_path / "trades.db", local_position_path=local_position, scheduler_health_path=scheduler)

    assert result["status"] == "FAIL"
    assert "Broker/local position consistency" in result["failures"]
    assert json.loads(pause_path.read_text(encoding="utf-8"))["paused"] is True


def test_readiness_passes_when_all_sources_are_flat(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    scheduler = reports_dir / "scheduler_health.json"
    scheduler.write_text(json.dumps({"trade_date": "2026-07-22", "tasks": [{"task": "Daily Trade Email", "status": "scheduled"}]}), encoding="utf-8")
    monkeypatch.setattr(readiness, "_cockpit_status", lambda: {"bot_running_effective": True})
    _configure_channels(monkeypatch)

    result = readiness.build_morning_readiness(datetime(2026, 7, 22, 9, 0, tzinfo=ZoneInfo("America/New_York")), _flat_broker, reports_dir=reports_dir, db_path=tmp_path / "trades.db", local_position_path=tmp_path / "open_position.json", scheduler_health_path=scheduler)

    assert result["status"] == "PASS"
    assert result["passed_checks"] == result["total_checks"] == 12