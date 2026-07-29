"""Fail-closed morning operational readiness check for live trading."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any, Callable
from urllib.request import urlopen
from zoneinfo import ZoneInfo

EASTERN_TZ = ZoneInfo("America/New_York")
READINESS_TIME_ET = dt_time(9, 0)
REPORTS_DIR = Path("reports")
DB_PATH = Path("data/mcleod_alpha.db")
LOCAL_POSITION_PATH = Path("data/open_position.json")
ENTRY_PAUSE_PATH = Path("data/entry_pause.json")
SCHEDULER_HEALTH_PATH = REPORTS_DIR / "scheduler_health.json"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _cockpit_status() -> dict[str, Any]:
    try:
        with urlopen("http://127.0.0.1:5001/api/status", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _ledger_symbols(db_path: Path) -> list[str]:
    try:
        with sqlite3.connect(db_path) as connection:
            rows = connection.execute("SELECT option_symbol FROM trade_log WHERE exit_time IS NULL").fetchall()
        return sorted(str(row[0] or "").strip() for row in rows)
    except sqlite3.Error:
        return []


def _broker_symbols(positions: list[dict[str, Any]] | None) -> list[str]:
    symbols: list[str] = []
    for position in positions or []:
        instrument = position.get("instrument") or {}
        quantity = float(position.get("longQuantity") or 0) - float(position.get("shortQuantity") or 0)
        symbol = str(instrument.get("symbol") or "").strip()
        if instrument.get("assetType") == "OPTION" and "SPY" in symbol and quantity:
            symbols.append(symbol)
    return sorted(symbols)


def _email_config() -> dict[str, str]:
    username = os.getenv("SMTP_USERNAME", "").strip() or os.getenv("EMAIL_ADDRESS", "").strip()
    password = (
        os.getenv("SMTP_PASSWORD", "").strip()
        or os.getenv("EMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    )
    host = os.getenv("SMTP_HOST", "").strip() or (
        "smtp.gmail.com" if username.lower().endswith("@gmail.com") else ""
    )
    sender = os.getenv("SMTP_FROM", "").strip() or os.getenv("EMAIL_ADDRESS", "").strip() or username
    recipient = (
        os.getenv("DAILY_BOT_REVIEW_TO_EMAIL", "").strip()
        or os.getenv("DAILY_TRADE_LOG_TO_EMAIL", "").strip()
        or os.getenv("DAILY_PNL_TO_EMAIL", "").strip()
        or os.getenv("EMAIL_TO", "").strip()
    )
    return {
        "host": host,
        "username": username,
        "password": password,
        "sender": sender,
        "recipient": recipient,
    }


def _email_ok() -> bool:
    return all(_email_config().values())


def _sms_status() -> tuple[bool, str]:
    enabled = os.getenv("ENABLE_TRADE_SMS_ALERTS", "false").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return True, "optional SMS alerts disabled"

    transport = os.getenv("TRADE_ALERT_TRANSPORT", "email_sms").strip().lower()
    gateway_ok = bool(os.getenv("TRADE_ALERT_TO_GATEWAY", "").strip())
    email_sms_ok = transport == "email_sms" and gateway_ok and _email_ok()
    outlook_sms_ok = transport == "outlook_sms" and gateway_ok
    twilio_ok = transport == "twilio" and all(
        os.getenv(key, "").strip()
        for key in (
            "TWILIO_ACCOUNT_SID",
            "TWILIO_AUTH_TOKEN",
            "TWILIO_FROM_NUMBER",
            "TRADE_ALERT_TO_NUMBER",
        )
    )
    if email_sms_ok or outlook_sms_ok or twilio_ok:
        return True, f"enabled {transport} transport configured"
    return False, f"enabled {transport} transport configuration incomplete"


def build_morning_readiness(
    now_et: datetime,
    broker_snapshot_provider: Callable[[], tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None, int | None, str | None]],
    *, reports_dir: Path = REPORTS_DIR, db_path: Path = DB_PATH,
    local_position_path: Path = LOCAL_POSITION_PATH, scheduler_health_path: Path = SCHEDULER_HEALTH_PATH,
    entry_pause_path: Path | None = None,
) -> dict[str, Any]:
    now = now_et.astimezone(EASTERN_TZ)
    checks: list[dict[str, Any]] = []
    entry_pause_path = entry_pause_path or ENTRY_PAUSE_PATH

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "status": "PASS" if passed else "FAIL", "passed": passed, "detail": detail})

    positions, _orders, broker_status, broker_error = broker_snapshot_provider()
    broker = _broker_symbols(positions)
    cockpit = _cockpit_status()
    scheduler = _load_json(scheduler_health_path)
    entry_pause = _load_json(entry_pause_path)
    email_task = next(
        (
            task
            for task in scheduler.get("tasks", [])
            if task.get("task") in {"Daily Bot Trade Review Email", "Daily Trade Email"}
        ),
        {},
    )
    scheduler_ok = scheduler.get("trade_date") == now.date().isoformat() and email_task.get("status") in {"scheduled", "healthy"}
    local_symbol = str(_load_json(local_position_path).get("option_symbol") or "").strip()
    local = [local_symbol] if local_symbol else []
    ledger = _ledger_symbols(db_path)
    add("Broker connected", broker_status == 200, f"status={broker_status} error={broker_error or 'none'}")
    add("Cockpit running", bool(cockpit), "loopback status available" if cockpit else "loopback status unavailable")
    add("Live monitor running", bool(cockpit.get("bot_running_effective")), f"bot_running_effective={cockpit.get('bot_running_effective')}")
    entries_paused = bool(entry_pause.get("paused"))
    pause_reason = str(entry_pause.get("reason") or "operator pause")
    pause_updated_at = str(entry_pause.get("updated_at") or "unknown time")
    add(
        "Trade entries active",
        not entries_paused,
        "entry admission is active" if not entries_paused else f"entries are paused: {pause_reason} (updated {pause_updated_at}); resume entries before trading",
    )
    add("Scheduler healthy", scheduler_ok, f"daily_email_status={email_task.get('status', 'missing')}")
    email_ok = _email_ok()
    email_config = _email_config()
    add(
        "Review email configured",
        email_ok,
        (
            f"transport={email_config['host']} recipient={email_config['recipient']}"
            if email_ok
            else "unified daily-review email configuration incomplete"
        ),
    )
    sms_ok, sms_detail = _sms_status()
    add("SMS policy satisfied", sms_ok, sms_detail)
    add("Broker/local position consistency", broker == local, f"broker={broker} local={local}")
    add("Broker/trade ledger consistency", broker == ledger, f"broker={broker} ledger={ledger}")
    probe = reports_dir / ".morning_readiness_probe"
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
        probe.write_text(now.isoformat(), encoding="utf-8")
        probe.unlink()
        writable = True
    except OSError:
        writable = False
    add("Research reports writable", writable, f"path={reports_dir}")
    add("Disk space sufficient", shutil.disk_usage(reports_dir).free >= 5 * 1024 ** 3, "at least 5 GB free")
    add("Clock and timezone correct", now.tzinfo == EASTERN_TZ, f"now_et={now.isoformat()}")
    add("Market calendar loaded", now.weekday() < 5, "weekday calendar available" if now.weekday() < 5 else "market closed weekend")
    failures = [check["name"] for check in checks if not check["passed"]]
    payload = {"generated_at": now.isoformat(), "trade_date": now.date().isoformat(), "status": "PASS" if not failures else "FAIL", "checks": checks, "passed_checks": len(checks) - len(failures), "total_checks": len(checks), "failures": failures, "entry_approval": "APPROVED" if not failures else "NOT_APPROVED"}
    _save_json(reports_dir / f"morning_readiness_{payload['trade_date']}.json", payload)
    if failures:
        _save_json(entry_pause_path, {"paused": True, "reason": "morning_readiness_failed", "failures": failures, "updated_at": now.isoformat()})
    return payload


def maybe_generate_morning_readiness(broker_snapshot_provider: Callable[[], tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None, int | None, str | None]], now_et: datetime | None = None) -> dict[str, Any] | None:
    now = (now_et or datetime.now(EASTERN_TZ)).astimezone(EASTERN_TZ)
    report_path = REPORTS_DIR / f"morning_readiness_{now.date().isoformat()}.json"
    if now.weekday() >= 5 or now.time() < READINESS_TIME_ET:
        return None
    return _load_json(report_path) if report_path.exists() else build_morning_readiness(now, broker_snapshot_provider)
