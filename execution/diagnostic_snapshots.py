"""Shared, broker-neutral diagnostic snapshot serialization."""

from __future__ import annotations

from datetime import datetime
import json
from zoneinfo import ZoneInfo


EASTERN_TZ = ZoneInfo("America/New_York")


def extract_entry_diagnostic_snapshot(feature_payload_text: str | None) -> str | None:
    """Return the complete durable entry diagnostic payload for later trade review."""
    if not feature_payload_text:
        return None
    try:
        payload = json.loads(feature_payload_text)
        if not isinstance(payload, dict):
            return None
        snapshot = dict(payload)
        snapshot["captured_at"] = snapshot.get("captured_at") or datetime.now(EASTERN_TZ).isoformat()
        return json.dumps(snapshot)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None