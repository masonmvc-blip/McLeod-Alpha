"""Append-only telemetry for protective-stop research and operational review."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


EASTERN_TZ = ZoneInfo("America/New_York")
STOP_TELEMETRY_DIR = Path(os.getenv("STOP_TELEMETRY_DIR", "data/reports/stop_telemetry"))


def record_stop_event(event_type: str, **fields: Any) -> None:
    """Best-effort immutable stop event; telemetry must never affect execution."""
    try:
        timestamp = datetime.now(EASTERN_TZ)
        path = STOP_TELEMETRY_DIR / f"protective_stop_events_{timestamp.date().isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"recorded_at": timestamp.isoformat(), "event_type": event_type, **fields}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
    except Exception:
        pass