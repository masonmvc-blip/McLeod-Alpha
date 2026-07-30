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
    monkeypatch.setenv("DAILY_BOT_REVIEW_TO_EMAIL", "review@example.test")
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

    result = readiness.build_morning_readiness(datetime(2026, 7, 22, 9, 0, tzinfo=ZoneInfo("America/New_York")), _flat_broker, reports_dir=reports_dir, db_path=tmp_path / "trades.db", local_position_path=tmp_path / "open_position.json", scheduler_health_path=scheduler, entry_pause_path=tmp_path / "entry_pause.json")

    assert result["status"] == "PASS"
    assert result["passed_checks"] == result["total_checks"] == 13


def test_readiness_fails_and_explains_when_entries_are_paused(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    scheduler = reports_dir / "scheduler_health.json"
    scheduler.write_text(json.dumps({"trade_date": "2026-07-22", "tasks": [{"task": "Daily Trade Email", "status": "scheduled"}]}), encoding="utf-8")
    pause_path = tmp_path / "entry_pause.json"
    pause_path.write_text(json.dumps({"paused": True, "reason": "operator pause", "updated_at": "2026-07-22T08:55:00-04:00"}), encoding="utf-8")
    monkeypatch.setattr(readiness, "_cockpit_status", lambda: {"bot_running_effective": True})
    _configure_channels(monkeypatch)

    result = readiness.build_morning_readiness(
        datetime(2026, 7, 22, 9, 0, tzinfo=ZoneInfo("America/New_York")),
        _flat_broker,
        reports_dir=reports_dir,
        db_path=tmp_path / "trades.db",
        local_position_path=tmp_path / "open_position.json",
        scheduler_health_path=scheduler,
        entry_pause_path=pause_path,
    )

    pause_check = next(check for check in result["checks"] if check["name"] == "Trade entries active")
    assert result["status"] == "FAIL"
    assert "Trade entries active" in result["failures"]
    assert pause_check["status"] == "FAIL"
    assert "entries are paused: operator pause" in pause_check["detail"]


def test_readiness_accepts_gmail_compatible_review_credentials_and_disabled_sms(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    scheduler = reports_dir / "scheduler_health.json"
    scheduler.write_text(
        json.dumps(
            {
                "trade_date": "2026-07-22",
                "tasks": [{"task": "Daily Bot Trade Review Email", "status": "scheduled"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(readiness, "_cockpit_status", lambda: {"bot_running_effective": True})
    monkeypatch.setenv("EMAIL_ADDRESS", "bot@gmail.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "app password")
    monkeypatch.setenv("DAILY_BOT_REVIEW_TO_EMAIL", "review@example.test")
    monkeypatch.setenv("ENABLE_TRADE_SMS_ALERTS", "false")
    for key in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"):
        monkeypatch.delenv(key, raising=False)

    result = readiness.build_morning_readiness(
        datetime(2026, 7, 22, 9, 0, tzinfo=ZoneInfo("America/New_York")),
        _flat_broker,
        reports_dir=reports_dir,
        db_path=tmp_path / "trades.db",
        local_position_path=tmp_path / "open_position.json",
        scheduler_health_path=scheduler,
        entry_pause_path=tmp_path / "entry_pause.json",
    )

    email_check = next(check for check in result["checks"] if check["name"] == "Review email configured")
    sms_check = next(check for check in result["checks"] if check["name"] == "SMS policy satisfied")
    assert result["status"] == "PASS"
    assert email_check["detail"] == "transport=smtp.gmail.com recipient=review@example.test"
    assert sms_check["detail"] == "optional SMS alerts disabled"


def test_readiness_fails_when_enabled_sms_transport_is_incomplete(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    scheduler = reports_dir / "scheduler_health.json"
    scheduler.write_text(
        json.dumps(
            {
                "trade_date": "2026-07-22",
                "tasks": [{"task": "Daily Bot Trade Review Email", "status": "scheduled"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(readiness, "_cockpit_status", lambda: {"bot_running_effective": True})
    monkeypatch.setenv("EMAIL_ADDRESS", "bot@gmail.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "app password")
    monkeypatch.setenv("DAILY_BOT_REVIEW_TO_EMAIL", "review@example.test")
    monkeypatch.setenv("ENABLE_TRADE_SMS_ALERTS", "true")
    monkeypatch.setenv("TRADE_ALERT_TRANSPORT", "twilio")
    for key in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "TRADE_ALERT_TO_NUMBER"):
        monkeypatch.delenv(key, raising=False)

    result = readiness.build_morning_readiness(
        datetime(2026, 7, 22, 9, 0, tzinfo=ZoneInfo("America/New_York")),
        _flat_broker,
        reports_dir=reports_dir,
        db_path=tmp_path / "trades.db",
        local_position_path=tmp_path / "open_position.json",
        scheduler_health_path=scheduler,
        entry_pause_path=tmp_path / "entry_pause.json",
    )

    assert "SMS policy satisfied" in result["failures"]


def test_readiness_accepts_enabled_outlook_sms(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_TRADE_SMS_ALERTS", "true")
    monkeypatch.setenv("TRADE_ALERT_TRANSPORT", "outlook_sms")
    monkeypatch.setenv("TRADE_ALERT_TO_GATEWAY", "123@example.test")
    monkeypatch.setattr(readiness, "_email_ok", lambda: True)

    assert readiness._sms_status() == (
        True,
        "enabled outlook_sms transport with authenticated SMTP fallback configured",
    )


def test_readiness_rejects_outlook_sms_without_fallback(monkeypatch):
    monkeypatch.setenv("ENABLE_TRADE_SMS_ALERTS", "true")
    monkeypatch.setenv("TRADE_ALERT_TRANSPORT", "outlook_sms")
    monkeypatch.setenv("TRADE_ALERT_TO_GATEWAY", "123@example.test")
    monkeypatch.setattr(readiness, "_email_ok", lambda: False)

    assert readiness._sms_status() == (
        False,
        "enabled outlook_sms transport configuration incomplete",
    )
