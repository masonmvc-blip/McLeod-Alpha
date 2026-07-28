"""Research-only post-trade analysis. This module never returns live instructions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from statistics import mean
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESEARCH_DB = PROJECT_ROOT / "data" / "strategy_research.db"
EXIT_STRATEGIES = (
    "CURRENT_EXIT", "EMA10_TRAILING", "SWING_LOW_TRAILING", "ATR_TRAILING",
    "MACD_MOMENTUM", "FIXED_5_PCT", "FIXED_7_PCT", "FIXED_10_PCT", "PARTIAL_5_PCT_EMA10",
)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bounded(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def _snapshot(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def classify_trend_strength(features: dict[str, Any]) -> str:
    """Classify trend strength from objective supplied indicator facts."""
    close, vwap = _number(features.get("close")), _number(features.get("vwap"))
    ema10, ema20, ema50 = (_number(features.get(name)) for name in ("ema10", "ema20", "ema50"))
    ema_slope, macd, rsi, volume_ratio = (_number(features.get(name)) for name in ("ema10_slope", "macd_histogram", "rsi", "volume_ratio"))
    score = 0
    if None not in (ema10, ema20, ema50) and (ema10 > ema20 > ema50 or ema10 < ema20 < ema50):
        score += 2
    if ema_slope is not None and abs(ema_slope) > 0:
        score += 1
    if None not in (close, vwap) and abs(close - vwap) / max(abs(vwap), 0.000001) >= 0.001:
        score += 1
    if macd is not None and abs(macd) > 0:
        score += 1
    if rsi is not None and (rsi >= 60 or rsi <= 40):
        score += 1
    if volume_ratio is not None and volume_ratio >= 1.25:
        score += 1
    return ("EXCEPTIONAL_TREND" if score >= 6 else "STRONG_TREND" if score >= 4
            else "MODERATE_TREND" if score >= 2 else "WEAK_TREND")


def independent_quality_scores(trade: dict[str, Any]) -> dict[str, float]:
    """Score decision quality without using realized profit or loss as an input."""
    entry = _snapshot(trade.get("entry_diagnostic_snapshot") or trade.get("feature_payload"))
    exit_snapshot = _snapshot(trade.get("exit_diagnostic_snapshot"))
    setup = 40.0 + min(35.0, max(0.0, _number(entry.get("confidence_score")) or 0.0) * 10.0)
    if str(trade.get("direction") or "").upper() in {"CALL", "PUT"}:
        setup += 10.0
    execution = 45.0 + (15.0 if trade.get("broker_entry_order_id") else 0.0)
    if _number(trade.get("option_entry")) and _number(trade.get("option_quantity")):
        execution += 15.0
    exit = 35.0 + max(0.0, min(50.0, _number(trade.get("exit_efficiency_pct")) or 0.0))
    if trade.get("broker_exit_order_id"):
        exit += 10.0
    decision = 35.0 + (20.0 if entry else 0.0) + (20.0 if exit_snapshot else 0.0)
    if str(trade.get("exit_reason") or "").strip():
        decision += 15.0
    return {"setup_quality_score": _bounded(setup), "execution_quality_score": _bounded(execution),
            "exit_quality_score": _bounded(exit), "decision_quality_score": _bounded(decision)}


def _shadow_exit(price_path: list[dict[str, Any]], entry: float, strategy: str, current_exit: float) -> dict[str, Any]:
    if strategy == "CURRENT_EXIT":
        return {"status": "AVAILABLE", "exit_price": current_exit, "exit_index": None}
    if not price_path:
        return {"status": "UNAVAILABLE_EVIDENCE", "reason": "TIMESTAMPED_OPTION_PRICE_PATH_REQUIRED"}
    for index, point in enumerate(price_path):
        price = _number(point.get("option_price"))
        if price is None:
            continue
        target = {"FIXED_5_PCT": 1.05, "FIXED_7_PCT": 1.07, "FIXED_10_PCT": 1.10}.get(strategy)
        if target is not None and price >= entry * target:
            return {"status": "AVAILABLE", "exit_price": price, "exit_index": index}
        threshold_key = {"EMA10_TRAILING": "ema10_option", "SWING_LOW_TRAILING": "swing_low_option", "ATR_TRAILING": "atr_trailing_option"}.get(strategy)
        if threshold_key and (threshold := _number(point.get(threshold_key))) is not None and price <= threshold:
            return {"status": "AVAILABLE", "exit_price": price, "exit_index": index}
        if strategy == "MACD_MOMENTUM" and (_number(point.get("macd_histogram")) or 0.0) < 0:
            return {"status": "AVAILABLE", "exit_price": price, "exit_index": index}
    return {"status": "AVAILABLE", "exit_price": _number(price_path[-1].get("option_price")) or current_exit, "exit_index": len(price_path) - 1}


def simulate_exit_strategies(trade: dict[str, Any], price_path: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    entry, current_exit = _number(trade.get("option_entry")), _number(trade.get("option_exit"))
    if entry is None or entry <= 0 or current_exit is None:
        return {strategy: {"status": "UNAVAILABLE_EVIDENCE", "reason": "OPTION_ENTRY_AND_EXIT_REQUIRED"} for strategy in EXIT_STRATEGIES}
    results = {strategy: _shadow_exit(price_path or [], entry, strategy, current_exit) for strategy in EXIT_STRATEGIES if strategy != "PARTIAL_5_PCT_EMA10"}
    if not price_path:
        results["PARTIAL_5_PCT_EMA10"] = {"status": "UNAVAILABLE_EVIDENCE", "reason": "TIMESTAMPED_OPTION_PRICE_PATH_REQUIRED"}
    else:
        fixed = results["FIXED_5_PCT"]
        trailing = results["EMA10_TRAILING"]
        if fixed.get("status") == trailing.get("status") == "AVAILABLE":
            price = round((float(fixed["exit_price"]) + float(trailing["exit_price"])) / 2.0, 6)
            results["PARTIAL_5_PCT_EMA10"] = {"status": "AVAILABLE", "exit_price": price, "exit_index": trailing.get("exit_index")}
        else:
            results["PARTIAL_5_PCT_EMA10"] = {"status": "UNAVAILABLE_EVIDENCE", "reason": "PARTIAL_EXIT_INPUTS_UNAVAILABLE"}
    for result in results.values():
        if result.get("status") == "AVAILABLE" and result.get("exit_price") is not None:
            result["return_pct"] = round(((float(result["exit_price"]) - entry) / entry) * 100.0, 4)
    return results


class StrategyResearchStore:
    """Dedicated append-only research database; never read by live rule code."""

    def __init__(self, path: Path | str = DEFAULT_RESEARCH_DB):
        self.path = Path(path)

    def record(self, analysis: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS completed_trade_research (trade_key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            connection.execute("INSERT OR REPLACE INTO completed_trade_research (trade_key, payload) VALUES (?, ?)", (analysis["trade_key"], json.dumps(analysis, sort_keys=True)))

    def expectancy(self) -> dict[str, dict[str, dict[str, float]]]:
        with sqlite3.connect(self.path) as connection:
            rows = [json.loads(row[0]) for row in connection.execute("SELECT payload FROM completed_trade_research")]
        dimensions = {
            "trend_strength": "trend_strength", "setup_type": "setup_type",
            "time_of_day": "time_of_day", "direction": "direction",
            "checklist_score": "checklist_score", "market_regime": "market_regime",
            "exit_strategy": "exit_strategy",
        }
        result: dict[str, dict[str, dict[str, float]]] = {}
        for name, field in dimensions.items():
            buckets: dict[str, list[float]] = {}
            for row in rows:
                value = str(row.get(field, "UNKNOWN") if row.get(field) is not None else "UNKNOWN")
                outcome = _number(row.get("outcome_pct"))
                if outcome is not None:
                    buckets.setdefault(value, []).append(outcome)
            result[name] = {key: {"count": len(values), "expectancy_pct": round(mean(values), 4), "win_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 2)} for key, values in buckets.items()}
        return result


def analyze_completed_trade(trade: dict[str, Any], *, price_path: list[dict[str, Any]] | None = None, store: StrategyResearchStore | None = None) -> dict[str, Any]:
    """Create and persist a research-only trade analysis without live-policy outputs."""
    exit_simulations = simulate_exit_strategies(trade, price_path)
    outcome = _number(trade.get("option_pnl_pct"))
    if outcome is None:
        entry, exit_price = _number(trade.get("option_entry")), _number(trade.get("option_exit"))
        outcome = ((exit_price - entry) / entry * 100.0) if entry and exit_price is not None else None
    features = _snapshot(trade.get("entry_diagnostic_snapshot") or trade.get("feature_payload"))
    trade_key = str(trade.get("broker_exit_order_id") or trade.get("broker_entry_order_id") or f"{trade.get('entry_time')}:{trade.get('option_symbol')}")
    entry_time = str(trade.get("entry_time") or "")
    time_of_day = entry_time.split("T", 1)[1][:5] if "T" in entry_time else "UNKNOWN"
    analysis = {"trade_key": trade_key, "research_only": True, "direction": str(trade.get("direction") or "UNKNOWN").upper(), "setup_type": str(features.get("setup_type") or "UNKNOWN"), "market_regime": str(features.get("regime") or "UNKNOWN"), "checklist_score": _number(features.get("confidence_score")), "time_of_day": time_of_day, "trend_strength": classify_trend_strength(features), "exit_strategy": "CURRENT_EXIT", "exit_price": _number(trade.get("option_exit")), "mfe_pct": _number(trade.get("mfe_pct")), "mae_pct": _number(trade.get("mae_pct")), "outcome_pct": round(outcome, 4) if outcome is not None else None, "scores": independent_quality_scores(trade), "exit_simulations": exit_simulations, "promotion_status": "RESEARCH_ONLY_INSUFFICIENT_SAMPLE"}
    (store or StrategyResearchStore()).record(analysis)
    return analysis