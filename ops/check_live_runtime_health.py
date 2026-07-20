#!/usr/bin/env python3
"""Fail-closed iMac runtime health monitor for the live entry window."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EASTERN = ZoneInfo("America/New_York")
STATUS_URL = os.getenv("MCLEOD_CANONICAL_CONTROL_CENTER_URL", "https://masons-imac.tailb88bd7.ts.net/").rstrip("/") + "/api/status"
STATE_PATH = ROOT / "data" / "live_runtime_health_state.json"
EVENT_PATH = ROOT / "data" / "reports" / "runtime_events.jsonl"
LATENCY_PATH = ROOT / "data" / "reports" / "latency_cycle_history.jsonl"


def _is_entry_window() -> bool:
    now = datetime.now(EASTERN)
    return now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) < (15, 45)


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _status() -> dict:
    context = ssl._create_unverified_context() if STATUS_URL.startswith("https://") else None
    request = urllib.request.Request(STATUS_URL, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, context=context, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def _latest_candle_issue() -> str | None:
    try:
        lines = LATENCY_PATH.read_text(encoding="utf-8").splitlines()
        event = json.loads(lines[-1]) if lines else {}
        source = str(event.get("candle_source") or "")
        timestamp = datetime.fromisoformat(str(event.get("ts_et")).replace("Z", "+00:00"))
        age = (datetime.now(EASTERN) - timestamp.astimezone(EASTERN)).total_seconds()
        if age > 150:
            return f"latest candle telemetry is {age:.0f}s old"
        if source.startswith("stale_") or source == "empty":
            return f"latest candle source is {source}"
    except Exception as exc:
        return f"candle telemetry unavailable: {type(exc).__name__}"
    return None


def _record(issues: list[str]) -> None:
    now = datetime.now(EASTERN).isoformat()
    state = _load_json(STATE_PATH)
    signature = " | ".join(issues)
    previous = str(state.get("signature") or "")
    payload = {"active": bool(issues), "signature": signature, "updated_at": now}
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not issues or signature == previous:
        return
    EVENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": now, "event_type": "live_runtime_health_failed", "severity": "error", "message": signature}) + "\n")
    try:
        from execution.sms_alerts import send_emergency_alert
        send_emergency_alert("Live runtime health failed", signature)
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    if not args.preflight and not _is_entry_window():
        return 0
    issues: list[str] = []
    try:
        status = _status()
    except Exception as exc:
        issues.append(f"iMac Control Center unavailable: {type(exc).__name__}")
    else:
        expected = {
            "bot_running_effective": True,
            "heartbeat_ok": True,
            "broker_reconciliation": "SUCCESS",
            "account_verified": True,
            "parity_state": "MATCH",
            "parity_block_start": False,
        }
        for key, value in expected.items():
            actual = status.get(key)
            if actual != value:
                issues.append(f"{key}={actual!r}, expected {value!r}")
        if status.get("last_error"):
            issues.append(f"last_error={status['last_error']}")
        candle_issue = _latest_candle_issue()
        if candle_issue:
            issues.append(candle_issue)
    _record(issues)
    print("live_runtime_health=" + ("PASS" if not issues else "FAIL") + ("" if not issues else " | " + " | ".join(issues)))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())