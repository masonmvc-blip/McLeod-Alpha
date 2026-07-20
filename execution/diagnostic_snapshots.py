"""Shared, broker-neutral diagnostic snapshot serialization."""

from __future__ import annotations

from datetime import datetime
import json
from zoneinfo import ZoneInfo


EASTERN_TZ = ZoneInfo("America/New_York")


def extract_entry_diagnostic_snapshot(feature_payload_text: str | None) -> str | None:
    """Return the durable entry diagnostic subset from a feature payload."""
    if not feature_payload_text:
        return None
    try:
        payload = json.loads(feature_payload_text)
        if not isinstance(payload, dict):
            return None
        snapshot = {
            "captured_at": payload.get("captured_at") or datetime.now(EASTERN_TZ).isoformat(),
            "vwap": payload.get("vwap"),
            "trend_stage": payload.get("trend_stage"),
            "continuation_quality_score": payload.get("continuation_quality_score"),
            "momentum_acceleration_score": payload.get("momentum_acceleration_score"),
            "absorption_score": payload.get("absorption_score"),
            "confidence_score": payload.get("confidence_score"),
            "trend_lifecycle_call": payload.get("trend_lifecycle_call"),
            "trend_lifecycle_put": payload.get("trend_lifecycle_put"),
            "continuation_quality_call": payload.get("continuation_quality_call"),
            "continuation_quality_put": payload.get("continuation_quality_put"),
            "trend_stage_call": payload.get("trend_stage_call"),
            "trend_stage_put": payload.get("trend_stage_put"),
            "confidence_score_call": payload.get("confidence_score_call"),
            "confidence_score_put": payload.get("confidence_score_put"),
        }
        return json.dumps(snapshot)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None