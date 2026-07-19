#!/usr/bin/env python3
"""Alert if decision audit logging stops during regular market hours."""

from __future__ import annotations

import json
import os
from datetime import datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from execution.sms_alerts import send_emergency_alert

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DECISION_AUDIT_PATH = Path(os.getenv("DECISION_AUDIT_PATH", str(PROJECT_ROOT / "data" / "reports" / "decision_audit_history.jsonl")))
STATE_PATH = PROJECT_ROOT / "logs" / "decision_audit_watchdog_state.json"
LOG_PATH = PROJECT_ROOT / "logs" / "decision_audit_watchdog.jsonl"
EASTERN_TZ = ZoneInfo("America/New_York")
ALERT_MAX_AGE_MINUTES = max(2, int(os.getenv("DECISION_AUDIT_MAX_AGE_MINUTES", "7")))
ALERT_COOLDOWN_MINUTES = max(5, int(os.getenv("DECISION_AUDIT_ALERT_COOLDOWN_MINUTES", "20")))


def _append_log(payload: Dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = dict(payload)
    record.setdefault("logged_at", datetime.now(timezone.utc).isoformat())
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _is_market_hours(now_et: datetime) -> bool:
    if now_et.weekday() >= 5:
        return False
    current = now_et.time()
    return dt_time(9, 30) <= current < dt_time(16, 0)


def _last_decision_event_ts() -> Optional[datetime]:
    if not DECISION_AUDIT_PATH.exists():
        return None

    try:
        last_line = ""
        with DECISION_AUDIT_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last_line = line.strip()
        if not last_line:
            return None
        payload = json.loads(last_line)
        ts = str(payload.get("ts_utc") or "").strip()
        if not ts:
            return None
        parsed = datetime.fromisoformat(ts)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def main() -> int:
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(EASTERN_TZ)

    if not _is_market_hours(now_et):
        _append_log({"event": "market_hours_skip", "now_et": now_et.isoformat()})
        return 0

    last_ts = _last_decision_event_ts()
    if last_ts is None:
        age_minutes = None
    else:
        age_minutes = max(0.0, (now_utc - last_ts).total_seconds() / 60.0)

    state = _load_state()
    last_alert_ts_raw = state.get("last_alert_ts")
    last_alert_ts = None
    if last_alert_ts_raw:
        try:
            last_alert_ts = datetime.fromisoformat(str(last_alert_ts_raw))
            if last_alert_ts.tzinfo is None:
                last_alert_ts = last_alert_ts.replace(tzinfo=timezone.utc)
            else:
                last_alert_ts = last_alert_ts.astimezone(timezone.utc)
        except Exception:
            last_alert_ts = None

    stale = age_minutes is None or age_minutes > ALERT_MAX_AGE_MINUTES
    cooldown_active = False
    if stale and last_alert_ts is not None:
        cooldown_active = ((now_utc - last_alert_ts).total_seconds() / 60.0) < ALERT_COOLDOWN_MINUTES

    _append_log({
        "event": "watchdog_check",
        "now_et": now_et.isoformat(),
        "last_decision_ts_utc": None if last_ts is None else last_ts.isoformat(),
        "age_minutes": age_minutes,
        "stale": stale,
        "cooldown_active": cooldown_active,
    })

    if not stale:
        state["last_ok_ts"] = now_utc.isoformat()
        _save_state(state)
        return 0

    if cooldown_active:
        return 0

    detail = (
        f"Decision audit has not logged a row for {age_minutes:.1f} minutes during market hours. "
        if age_minutes is not None
        else "Decision audit file has no readable rows during market hours. "
    )
    detail += f"Path: {DECISION_AUDIT_PATH}"

    send_emergency_alert("DECISION AUDIT WATCHDOG", detail)
    state["last_alert_ts"] = now_utc.isoformat()
    _save_state(state)
    _append_log({"event": "alert_sent", "detail": detail, "age_minutes": age_minutes})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
