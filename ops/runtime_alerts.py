"""Small durable alert flag shared by unattended operational jobs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALERT_PATH = ROOT / "data" / "runtime_alert_flag.json"
_SEVERITY_RANK = {
    "info": 0,
    "warning": 1,
    "error": 2,
    "critical": 3,
}


def set_runtime_alert(event_type: str, message: str, *, severity: str = "error") -> None:
    ALERT_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized_severity = str(severity or "error").strip().lower()
    try:
        current = json.loads(ALERT_PATH.read_text(encoding="utf-8"))
    except Exception:
        current = {}
    current_severity = str(current.get("severity") or "info").strip().lower()
    if (
        current.get("active") is True
        and current.get("event_type") != event_type
        and _SEVERITY_RANK.get(current_severity, 2)
        > _SEVERITY_RANK.get(normalized_severity, 2)
    ):
        return
    ALERT_PATH.write_text(
        json.dumps(
            {
                "active": True,
                "severity": normalized_severity,
                "event_type": event_type,
                "message": message,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def clear_runtime_alert(event_type: str) -> None:
    if not ALERT_PATH.exists():
        return
    try:
        payload = json.loads(ALERT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    if payload.get("event_type") != event_type:
        return
    payload.update(
        {
            "active": False,
            "message": "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    ALERT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
