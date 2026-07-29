"""Append-only telemetry for the Day Trade SPY research suite."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


EASTERN_TZ = ZoneInfo("America/New_York")
SHADOW_DIR = Path(
    os.getenv("DAY_TRADE_SPY_SHADOW_DIR", "data/reports/day_trade_spy_shadow")
)


def record_day_trade_spy_shadow(
    snapshot: dict[str, Any],
    *,
    event_phase: str,
    entered: bool = False,
    option_symbol: str | None = None,
) -> None:
    """Best-effort append only; this function returns no trading decision."""
    if os.getenv("PYTEST_CURRENT_TEST"):
        return
    try:
        now = datetime.now(EASTERN_TZ)
        payload = {
            **snapshot,
            "recorded_at": now.isoformat(),
            "event_type": "day_trade_spy_shadow_evaluation",
            "event_phase": str(event_phase),
            "live_engine_entered": bool(entered),
            "option_symbol": option_symbol,
            "shadow_only": True,
            "automatic_live_change_allowed": False,
        }
        path = SHADOW_DIR / f"day_trade_spy_shadow_{now.date().isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
    except Exception:
        # Research telemetry must never interrupt the monitor or order path.
        pass
