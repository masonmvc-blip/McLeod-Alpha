"""Observe accepted-breakout labels without influencing live execution."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd


OBSERVATION_DIR = Path(os.getenv("ACCEPTED_BREAKOUT_OBSERVATION_DIR", "data/reports/accepted_breakout_observations"))
MINIMUM_COMPLETED_TRADES_PER_COHORT = 100
_pending: dict[str, float] = {}


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def observe_candidate(candles: pd.DataFrame, direction: str, *, captured_at: datetime | None = None) -> dict[str, Any]:
    """Return an immutable shadow label. This function has no execution side effects."""
    normalized_direction = str(direction or "").upper()
    frame = candles.tail(7)
    if normalized_direction not in {"CALL", "PUT"} or len(frame) < 6:
        return {"accepted_breakout_observed": False, "accepted_breakout_reason": "insufficient_closed_candles"}
    close = _number(frame.iloc[-1].get("close"))
    high = _number(frame.iloc[-1].get("high"))
    low = _number(frame.iloc[-1].get("low"))
    trigger_slice = frame.iloc[-6:-1]
    trigger = max(float(value) for value in trigger_slice["high"].dropna()) if normalized_direction == "CALL" else min(float(value) for value in trigger_slice["low"].dropna())
    pending = _pending.get(normalized_direction)
    is_break = close is not None and ((close > trigger) if normalized_direction == "CALL" else (close < trigger))
    if is_break:
        _pending[normalized_direction] = trigger
        accepted, reason = False, "breakout_observed_awaiting_retest"
    elif pending is None:
        accepted, reason = False, "no_prior_breakout"
    else:
        touched = low is not None and low <= pending if normalized_direction == "CALL" else high is not None and high >= pending
        held = close is not None and ((close >= pending) if normalized_direction == "CALL" else (close <= pending))
        accepted = bool(touched and held)
        reason = "retest_hold_confirmed" if accepted else "retest_not_held"
        if accepted:
            _pending.pop(normalized_direction, None)
    timestamp = captured_at or datetime.now().astimezone()
    fingerprint = f"{timestamp.isoformat()}:{normalized_direction}:{close}:{trigger}"
    return {
        "accepted_breakout_observer_id": hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:20],
        "accepted_breakout_observed": True,
        "accepted_breakout_admit": accepted,
        "accepted_breakout_reason": reason,
        "accepted_breakout_trigger": round(trigger, 6),
        "accepted_breakout_close": close,
        "accepted_breakout_captured_at": timestamp.isoformat(),
    }


def record_candidate_observation(observation: dict[str, Any], *, feature_payload: dict[str, Any], option: dict[str, Any] | None) -> None:
    """Best-effort append only; failures are intentionally isolated from trading."""
    try:
        timestamp = datetime.now().astimezone()
        payload = {
            "schema_version": "accepted-breakout-observation.v1",
            "recorded_at": timestamp.isoformat(),
            **observation,
            "direction": feature_payload.get("direction"),
            "structural_room": (feature_payload.get("support_resistance") or {}),
            "option_symbol": (option or {}).get("symbol"),
            "bid": (option or {}).get("bid"),
            "ask": (option or {}).get("ask"),
            "mark": (option or {}).get("mark"),
        }
        path = OBSERVATION_DIR / f"accepted_breakout_candidates_{timestamp.date().isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
    except Exception:
        pass