"""Research-only, spread-aware option contract ranking.

The live selector remains authoritative.  This module only records which
otherwise-live-eligible contract a cost-aware policy would have preferred.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import date, datetime
import math
from statistics import pstdev
from typing import Any

from engine.brain.engine import (
    OPTION_MAX_ABSOLUTE_SPREAD,
    OPTION_MAX_SPREAD_PCT,
    OPTION_MIN_DAILY_VOLUME,
    OPTION_MIN_DAYS_TO_EXPIRY,
    OPTION_MIN_OPEN_INTEREST,
)
from execution.contract_limits import MAX_OPEN_CONTRACTS


MODEL_VERSION = "option-selection-shadow.v1"
HISTORY_SNAPSHOTS = 12
MIN_STABILITY_SAMPLES = 3
WEIGHTS = {
    "spread_tightness": 0.45,
    "liquidity": 0.25,
    "quote_stability": 0.20,
    "strike_proximity": 0.10,
}
_QUOTE_HISTORY: dict[str, deque[tuple[float, float]]] = defaultdict(
    lambda: deque(maxlen=HISTORY_SNAPSHOTS)
)


def reset_option_selection_shadow_history() -> None:
    """Clear process-local quote history (primarily for deterministic tests)."""
    _QUOTE_HISTORY.clear()


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _normalize(values: list[float], value: float, *, lower_is_better: bool) -> float:
    low = min(values)
    high = max(values)
    if high <= low:
        return 1.0
    score = (value - low) / (high - low)
    return round(1.0 - score if lower_is_better else score, 6)


def _eligible_expirations(expirations: dict[str, Any], as_of: date) -> list[str]:
    rows: list[tuple[date, str]] = []
    for key in expirations:
        try:
            expiry = datetime.strptime(str(key).split(":", 1)[0], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        if expiry.weekday() == 4 and (expiry - as_of).days >= OPTION_MIN_DAYS_TO_EXPIRY:
            rows.append((expiry, str(key)))
    return [key for _, key in sorted(rows)]


def _candidate_rows(
    option_chain: dict[str, Any],
    direction: str,
    underlying_price: float,
    live_selection: dict[str, Any] | None,
    *,
    as_of: date,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    direction = str(direction or "").upper()
    map_key = "callExpDateMap" if direction == "CALL" else "putExpDateMap"
    expirations = (option_chain or {}).get(map_key) or {}
    live_expiration = str((live_selection or {}).get("expiration") or "")
    expiry_keys = _eligible_expirations(expirations, as_of)
    if live_expiration:
        expiry_keys = [key for key in expiry_keys if key == live_expiration]

    nearest_open_interest_rows: tuple[list[dict[str, Any]], str] | None = None
    for expiration in expiry_keys:
        volume_rows: list[dict[str, Any]] = []
        oi_rows: list[dict[str, Any]] = []
        for strike, contracts in (expirations.get(expiration) or {}).items():
            for contract in contracts or []:
                bid = _number(contract.get("bid"))
                ask = _number(contract.get("ask"))
                mark = _number(contract.get("mark"))
                strike_price = _number(strike)
                if (
                    bid is None or ask is None or mark is None or strike_price is None
                    or bid <= 0 or ask <= 0 or mark <= 0
                ):
                    continue
                spread = ask - bid
                spread_pct = (spread / mark) * 100.0
                if (
                    spread < 0
                    or spread > OPTION_MAX_ABSOLUTE_SPREAD
                    or spread_pct > OPTION_MAX_SPREAD_PCT
                ):
                    continue
                volume = int(_number(contract.get("totalVolume")) or 0)
                open_interest = int(_number(contract.get("openInterest")) or 0)
                candidate = {
                    "symbol": str(contract.get("symbol") or ""),
                    "direction": direction,
                    "expiration": expiration,
                    "strike": strike_price,
                    "bid": bid,
                    "ask": ask,
                    "mark": mark,
                    "volume": volume,
                    "open_interest": open_interest,
                    "spread": round(spread, 4),
                    "spread_pct": round(spread_pct, 4),
                    "strike_distance": round(abs(strike_price - float(underlying_price)), 4),
                }
                if not candidate["symbol"]:
                    continue
                if volume >= OPTION_MIN_DAILY_VOLUME:
                    volume_rows.append(candidate)
                elif open_interest >= OPTION_MIN_OPEN_INTEREST:
                    oi_rows.append(candidate)
        if volume_rows:
            return volume_rows, expiration, "DAILY_VOLUME"
        if oi_rows and live_expiration:
            return oi_rows, expiration, "OPEN_INTEREST_FALLBACK"
        if oi_rows and nearest_open_interest_rows is None:
            # Match the live policy: remember the nearest OI fallback but continue
            # looking for daily-volume contracts in later eligible expirations.
            nearest_open_interest_rows = (oi_rows, expiration)
    if nearest_open_interest_rows:
        rows, expiration = nearest_open_interest_rows
        return rows, expiration, "OPEN_INTEREST_FALLBACK"
    return [], live_expiration or None, None


def _stability(candidate: dict[str, Any]) -> tuple[float, int]:
    history = _QUOTE_HISTORY[candidate["symbol"]]
    observation = (float(candidate["mark"]), float(candidate["spread_pct"]))
    if not history or history[-1] != observation:
        history.append(observation)
    samples = len(history)
    if samples < MIN_STABILITY_SAMPLES:
        return 0.5, samples
    marks = [row[0] for row in history]
    spreads = [row[1] for row in history]
    mark_cv = pstdev(marks) / max(sum(marks) / samples, 0.01)
    spread_cv = pstdev(spreads) / max(sum(spreads) / samples, 0.01)
    instability = min(1.0, (mark_cv * 4.0) + (spread_cv * 0.5))
    return round(1.0 - instability, 6), samples


def _snapshot(option: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(option, dict) or not option.get("symbol"):
        return None
    keys = (
        "symbol", "direction", "expiration", "strike", "bid", "ask", "mark",
        "volume", "open_interest", "spread", "spread_pct", "strike_distance",
    )
    return {key: option.get(key) for key in keys}


def build_option_selection_shadow(
    option_chain: dict[str, Any] | None,
    direction: str,
    underlying_price: float,
    live_selection: dict[str, Any] | None,
    *,
    as_of: date | None = None,
    quantity: int = MAX_OPEN_CONTRACTS,
) -> dict[str, Any]:
    """Rank live-eligible contracts without changing the production choice."""
    candidates, expiration, liquidity_tier = _candidate_rows(
        option_chain or {},
        direction,
        underlying_price,
        live_selection,
        as_of=as_of or date.today(),
    )
    base = {
        "schema_version": MODEL_VERSION,
        "shadow_only": True,
        "automatic_live_change_allowed": False,
        "direction": str(direction or "").upper(),
        "expiration": expiration,
        "liquidity_tier": liquidity_tier,
        "live_selection": _snapshot(live_selection),
        "weights": dict(WEIGHTS),
        "quantity_assumption": int(quantity),
    }
    if not candidates:
        return {
            **base,
            "valid": False,
            "reason": "No contracts passed the live selector's eligibility filters",
            "shadow_selection": None,
            "selection_differs": False,
            "ranked_candidates": [],
        }

    spreads = [float(row["spread_pct"]) for row in candidates]
    liquidity_values = [
        math.log1p(max(row["volume"], OPTION_MIN_DAILY_VOLUME))
        + 0.5 * math.log1p(max(row["open_interest"], 0))
        for row in candidates
    ]
    distances = [float(row["strike_distance"]) for row in candidates]
    ranked: list[dict[str, Any]] = []
    for candidate, liquidity_value in zip(candidates, liquidity_values):
        stability_score, stability_samples = _stability(candidate)
        components = {
            "spread_tightness": _normalize(
                spreads, float(candidate["spread_pct"]), lower_is_better=True
            ),
            "liquidity": _normalize(
                liquidity_values, liquidity_value, lower_is_better=False
            ),
            "quote_stability": stability_score,
            "strike_proximity": _normalize(
                distances, float(candidate["strike_distance"]), lower_is_better=True
            ),
        }
        total = sum(WEIGHTS[key] * components[key] for key in WEIGHTS)
        ranked.append({
            **candidate,
            "shadow_score": round(total, 6),
            "score_components": components,
            "quote_stability_samples": stability_samples,
            "quote_stability_ready": stability_samples >= MIN_STABILITY_SAMPLES,
        })
    ranked.sort(
        key=lambda row: (
            row["shadow_score"],
            -row["spread_pct"],
            row["volume"],
            row["open_interest"],
        ),
        reverse=True,
    )
    shadow = ranked[0]
    live = _snapshot(live_selection)
    live_spread = _number((live or {}).get("spread"))
    if live_spread is None and live:
        bid = _number(live.get("bid"))
        ask = _number(live.get("ask"))
        live_spread = ask - bid if bid is not None and ask is not None else None
    spread_saving = (
        live_spread - float(shadow["spread"])
        if live_spread is not None
        else None
    )
    return {
        **base,
        "valid": True,
        "reason": None,
        "shadow_selection": _snapshot(shadow),
        "selection_differs": bool(
            live and str(live.get("symbol")) != str(shadow.get("symbol"))
        ),
        "estimated_spread_saving_per_contract": (
            round(spread_saving * 100.0, 2) if spread_saving is not None else None
        ),
        "estimated_spread_saving_total": (
            round(spread_saving * 100.0 * int(quantity), 2)
            if spread_saving is not None else None
        ),
        "stability_evidence_ready": bool(
            shadow["quote_stability_ready"]
        ),
        "ranked_candidates": ranked[:5],
    }
