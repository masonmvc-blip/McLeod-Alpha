"""Read-only scheduler health projection for daily operational reports."""

from __future__ import annotations

import json
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


CENTRAL_TZ = ZoneInfo("America/Chicago")
REPORTS_DIR = Path("reports")
EMAIL_STATE_PATH = Path("data/daily_trade_log_email_state.json")
WATCHDOG_STATE_PATH = Path("data/scheduler_health_watchdog_state.json")
MISSED_EMAIL_ALERT_DELAY_MINUTES = 15
_LAST_REFRESH_MINUTE: str | None = None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _email_target_time() -> dt_time:
    from execution.daily_trade_log_email import _configured_send_time_ct

    return _configured_send_time_ct()


def _artifact_status(path: Path, trade_date: str) -> dict[str, Any]:
    if not path.exists():
        return {"status": "not_run", "last_result": "artifact missing", "last_run": None}
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=CENTRAL_TZ).isoformat()
    return {"status": "artifact_present", "last_result": f"generated for {trade_date}", "last_run": modified}


def _missed_email_alert_is_due(now_ct: datetime, target: dt_time, email_status: str) -> bool:
    if email_status != "missed" or now_ct.weekday() >= 5:
        return False
    target_at = now_ct.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
    return now_ct >= target_at + timedelta(minutes=MISSED_EMAIL_ALERT_DELAY_MINUTES)


def _maybe_alert_missed_daily_email(now_ct: datetime, target: dt_time, email_status: str) -> None:
    if not _missed_email_alert_is_due(now_ct, target, email_status):
        return

    trade_date = now_ct.date().isoformat()
    state = _load_json(WATCHDOG_STATE_PATH)
    if state.get("alert_date") == trade_date:
        return

    from execution.sms_alerts import send_emergency_alert

    delivered = send_emergency_alert(
        "DAILY TRADE EMAIL MISSED",
        (
            f"The {target.strftime('%H:%M')} CT daily trade email remains unsent after "
            f"{MISSED_EMAIL_ALERT_DELAY_MINUTES} minutes. Check Scheduler Health and SMTP delivery."
        ),
    )
    _save_json(
        WATCHDOG_STATE_PATH,
        {
            "alert_date": trade_date,
            "alert_at": now_ct.isoformat(),
            "alert_delivered": delivered,
            "reason": "daily_trade_email_missed",
        },
    )


def build_scheduler_health_dashboard(now_ct: datetime | None = None, reports_dir: Path = REPORTS_DIR) -> tuple[Path, Path]:
    now = now_ct or datetime.now(CENTRAL_TZ)
    now = now.replace(tzinfo=CENTRAL_TZ) if now.tzinfo is None else now.astimezone(CENTRAL_TZ)
    trade_date = now.date().isoformat()
    target = _email_target_time()
    state = _load_json(EMAIL_STATE_PATH)
    watchdog_state = _load_json(WATCHDOG_STATE_PATH)
    if state.get("last_sent_date") == trade_date:
        email_status = "healthy"
        email_result = "sent"
    elif now.weekday() < 5 and now.time() >= target:
        email_status = "missed"
        email_result = "scheduled time passed with no recorded send"
    else:
        email_status = "scheduled"
        email_result = "awaiting scheduled send time"

    tasks = [
        {
            "task": "Daily Trade Email",
            "schedule_ct": target.strftime("%H:%M"),
            "status": email_status,
            "last_result": email_result,
            "last_run": state.get("last_sent_at") or state.get("last_attempt_at"),
            "next_run": None if email_status == "healthy" else f"{trade_date} {target.strftime('%H:%M')} CT",
        },
    ]
    artifacts = [
        ("Opportunity Review", reports_dir / f"daily_opportunity_review_{trade_date}.json"),
        ("Research Validation", reports_dir / "validation_dashboard.json"),
        ("Daily Research Advisory", reports_dir / f"daily_research_advisory_{trade_date}.json"),
    ]
    for task, path in artifacts:
        status = _artifact_status(path, trade_date)
        tasks.append({"task": task, "schedule_ct": "after daily email export", "next_run": None, **status})

    payload = {
        "generated_at": now.isoformat(),
        "trade_date": trade_date,
        "tasks": tasks,
        "health_summary": "attention_required" if any(task["status"] in {"missed", "not_run"} for task in tasks) else "healthy",
        "missed_email_watchdog": {
            "delay_minutes": MISSED_EMAIL_ALERT_DELAY_MINUTES,
            "alert_due": _missed_email_alert_is_due(now, target, email_status),
            "alert_date": watchdog_state.get("alert_date"),
            "alert_at": watchdog_state.get("alert_at"),
            "alert_delivered": watchdog_state.get("alert_delivered"),
        },
        "note": "Artifact presence confirms generation only; email delivery is confirmed only by a recorded send state.",
    }
    json_path = reports_dir / "scheduler_health.json"
    html_path = reports_dir / "scheduler_health.html"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    headers = ["task", "schedule_ct", "status", "last_result", "last_run", "next_run"]
    header_html = "".join(f"<th>{header}</th>" for header in headers)
    rows = "".join("<tr>" + "".join(f"<td>{task.get(header)}</td>" for header in headers) + "</tr>" for task in tasks)
    html_path.write_text(
        "<html><head><meta charset='utf-8'><title>Scheduler Health</title></head><body>"
        f"<h1>Scheduler Health - {trade_date}</h1><p>{payload['note']}</p>"
        f"<table border='1' cellpadding='4' cellspacing='0'><tr>{header_html}</tr>{rows}</table></body></html>",
        encoding="utf-8",
    )
    return json_path, html_path


def maybe_generate_scheduler_health_dashboard(now_ct: datetime | None = None) -> None:
    global _LAST_REFRESH_MINUTE
    now = now_ct or datetime.now(CENTRAL_TZ)
    now = now.replace(tzinfo=CENTRAL_TZ) if now.tzinfo is None else now.astimezone(CENTRAL_TZ)
    minute = now.strftime("%Y-%m-%dT%H:%M")
    if minute == _LAST_REFRESH_MINUTE:
        return
    _LAST_REFRESH_MINUTE = minute
    target = _email_target_time()
    state = _load_json(EMAIL_STATE_PATH)
    email_status = "healthy" if state.get("last_sent_date") == now.date().isoformat() else "missed"
    _maybe_alert_missed_daily_email(now, target, email_status)
    build_scheduler_health_dashboard(now)