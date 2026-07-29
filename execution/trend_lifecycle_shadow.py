"""Append-only research telemetry for Trend Lifecycle V2."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


EASTERN_TZ = ZoneInfo("America/New_York")
SHADOW_DIR = Path(
    os.getenv("TREND_LIFECYCLE_SHADOW_DIR", "data/reports/trend_lifecycle_shadow")
)
_LAST_CANDLE_KEY: str | None = None


def record_lifecycle_shadow_snapshot(
    *,
    candle_time: Any,
    lifecycle: dict[str, Any],
    regime: str,
    call_score: int,
    put_score: int,
    candidate_direction: str | None,
    candle_source: str,
) -> None:
    """Best-effort write that is incapable of changing a trading decision."""
    global _LAST_CANDLE_KEY
    if os.getenv("PYTEST_CURRENT_TEST"):
        return
    try:
        now = datetime.now(EASTERN_TZ)
        candle_key = f"{candle_time}|{lifecycle.get('model_version')}"
        if candle_key == _LAST_CANDLE_KEY:
            return
        payload = {
            "schema_version": "trend-lifecycle-shadow.v1",
            "recorded_at": now.isoformat(),
            "trading_date": now.date().isoformat(),
            "candle_time": str(candle_time),
            "candle_source": candle_source,
            "regime": regime,
            "call_score": int(call_score),
            "put_score": int(put_score),
            "candidate_direction": candidate_direction,
            "lifecycle_v2": lifecycle,
            "shadow_only": True,
        }
        path = SHADOW_DIR / f"trend_lifecycle_shadow_{now.date().isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        # A restart can repeat the last completed candle. Avoid a duplicate
        # without scanning the full session file.
        if path.exists() and path.stat().st_size:
            with path.open("rb") as handle:
                handle.seek(max(0, path.stat().st_size - 8192))
                tail = handle.read().decode("utf-8", errors="ignore").splitlines()
            if tail:
                try:
                    previous = json.loads(tail[-1])
                    if str(previous.get("candle_time")) == str(candle_time):
                        _LAST_CANDLE_KEY = candle_key
                        return
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
        _LAST_CANDLE_KEY = candle_key
    except Exception:
        # Research telemetry is intentionally non-blocking.
        pass
