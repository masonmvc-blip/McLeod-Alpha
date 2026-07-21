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


def _smtp_ok() -> bool:
    return all(os.getenv(key, "").strip() for key in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD"))


def _sms_ok() -> bool:
    enabled = os.getenv("ENABLE_TRADE_SMS_ALERTS", "false").strip().lower() in {"1", "true", "yes", "on"}
    transport = os.getenv("TRADE_ALERT_TRANSPORT", "email_sms").strip().lower()
    return enabled and transport in {"email_sms", "outlook_sms"} and bool(os.getenv("TRADE_ALERT_TO_GATEWAY", "").strip())


def build_morning_readiness(
    now_et: datetime,
    broker_snapshot_provider: Callable[[], tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None, int | None, str | None]],
    *, reports_dir: Path = REPORTS_DIR, db_path: Path = DB_PATH,
    local_position_path: Path = LOCAL_POSITION_PATH, scheduler_health_path: Path = SCHEDULER_HEALTH_PATH,
) -> dict[str, Any]:
    now = now_et.astimezone(EASTERN_TZ)
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "status": "PASS" if passed else "FAIL", "passed": passed, "detail": detail})

    positions, _orders, broker_status, broker_error = broker_snapshot_provider()
    broker = _broker_symbols(positions)
    cockpit = _cockpit_status()
    scheduler = _load_json(scheduler_health_path)
    email_task = next((task for task in scheduler.get("tasks", []) if task.get("task") == "Daily Trade Email"), {})
    scheduler_ok = scheduler.get("trade_date") == now.date().isoformat() and email_task.get("status") in {"scheduled", "healthy"}
    local_symbol = str(_load_json(local_position_path).get("option_symbol") or "").strip()
    local = [local_symbol] if local_symbol else []
    ledger = _ledger_symbols(db_path)
    add("Broker connected", broker_status == 200, f"status={broker_status} error={broker_error or 'none'}")
    add("Cockpit running", bool(cockpit), "loopback status available" if cockpit else "loopback status unavailable")
    add("Live monitor running", bool(cockpit.get("bot_running_effective")), f"bot_running_effective={cockpit.get('bot_running_effective')}")
    add("Scheduler healthy", scheduler_ok, f"daily_email_status={email_task.get('status', 'missing')}")
    add("SMTP healthy", _smtp_ok(), "SMTP credentials configured" if _smtp_ok() else "SMTP configuration incomplete")
    add("SMS healthy", _sms_ok(), "approved SMS gateway configured" if _sms_ok() else "SMS gateway disabled or incomplete")
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
        _save_json(ENTRY_PAUSE_PATH, {"paused": True, "reason": "morning_readiness_failed", "failures": failures, "updated_at": now.isoformat()})
    return payload


def maybe_generate_morning_readiness(broker_snapshot_provider: Callable[[], tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None, int | None, str | None]], now_et: datetime | None = None) -> dict[str, Any] | None:
    now = (now_et or datetime.now(EASTERN_TZ)).astimezone(EASTERN_TZ)
    report_path = REPORTS_DIR / f"morning_readiness_{now.date().isoformat()}.json"
    if now.weekday() >= 5 or now.time() < READINESS_TIME_ET:
        return None
    return _load_json(report_path) if report_path.exists() else build_morning_readiness(now, broker_snapshot_provider)