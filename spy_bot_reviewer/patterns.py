"""Immutable, advisory-only pattern discovery for SPY replay bundles."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


class PatternDiscoveryEngine:
    """Build reproducible feature cohorts from already-captured replay evidence."""

    VERSION = "pattern-discovery.v1"
    MIN_SAMPLE_SIZE = 10
    HIGH_CONFIDENCE_SAMPLE_SIZE = 30

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.history_path = data_dir / "pattern_discovery_history.jsonl"

    def discover(self, bundles: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for bundle in bundles:
            for feature, value in self._features(bundle).items():
                if value is not None:
                    grouped.setdefault(f"{feature}:{value}", []).append(bundle)
        patterns = [self._summarize(name, rows) for name, rows in sorted(grouped.items())]
        patterns = [pattern for pattern in patterns if pattern["sample_size"] >= self.MIN_SAMPLE_SIZE]
        previous = self._latest_snapshot()
        previous_by_id = {pattern["pattern_id"]: pattern for pattern in (previous or {}).get("patterns", [])}
        for pattern in patterns:
            prior = previous_by_id.get(pattern["pattern_id"])
            pattern["trend"] = self._trend(pattern, prior)
            pattern["advisory_status"] = self._advisory_status(pattern)
        snapshot = {
            "schema_version": self.VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "pattern_count": len(patterns),
            "patterns": patterns,
            "policy": {
                "minimum_sample_size": self.MIN_SAMPLE_SIZE,
                "high_confidence_sample_size": self.HIGH_CONFIDENCE_SAMPLE_SIZE,
                "automatic_live_deployment": False,
                "requires_rule_validation": True,
            },
        }
        return self._append_if_changed(snapshot)

    def latest(self) -> Dict[str, Any]:
        return self._latest_snapshot() or {
            "schema_version": self.VERSION,
            "pattern_count": 0,
            "patterns": [],
            "policy": {"automatic_live_deployment": False, "requires_rule_validation": True},
        }

    def _features(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        trade = bundle.get("trade") or {}
        candles = ((bundle.get("candles") or {}).get("1m") or [])
        entry = candles[0] if candles else {}
        execution = bundle.get("execution") or {}
        scores = bundle.get("scores") or {}
        ema10 = self._number(entry.get("ema10")); ema20 = self._number(entry.get("ema20")); close = self._number(entry.get("close")); vwap = self._number(entry.get("vwap")); rsi = self._number(entry.get("rsi")); macd = self._number(entry.get("macd"))
        return {
            "regime": trade.get("market_regime") or "UNKNOWN",
            "direction": trade.get("direction") or self._option_direction(trade.get("option_symbol")),
            "volatility": self._volatility_bucket(candles),
            "trend_strength": "STRONG" if ema10 is not None and ema20 is not None and abs(ema10 - ema20) / max(abs(close or 1), 1) >= 0.001 else "WEAK",
            "ema_alignment": "BULLISH" if ema10 is not None and ema20 is not None and ema10 >= ema20 else "BEARISH",
            "vwap_relationship": "ABOVE" if close is not None and vwap is not None and close >= vwap else "BELOW",
            "rsi": self._bucket(rsi, (35, 45, 55, 65), ("OVERSOLD", "LOW", "NEUTRAL", "HIGH", "OVERBOUGHT")),
            "macd": "POSITIVE" if macd is not None and macd >= 0 else "NEGATIVE",
            "opening_range": self._opening_range_behavior(candles),
            "time_of_day": self._time_bucket(trade.get("entry_time")),
            "option_characteristics": self._option_characteristics(trade),
            "confidence": self._bucket(self._number(execution.get("confidence_score") or trade.get("entry_score")), (55, 70, 85), ("LOW", "MEDIUM", "HIGH", "VERY_HIGH")),
            "setup_quality": self._bucket(self._number(scores.get("Setup Quality")), (50, 70, 85), ("LOW", "MEDIUM", "HIGH", "VERY_HIGH")),
        }

    def _summarize(self, label: str, bundles: List[Dict[str, Any]]) -> Dict[str, Any]:
        metrics = [self._actual_metrics(bundle) for bundle in bundles]
        pnls = [metric["pnl"] for metric in metrics]
        wins = sum(1 for pnl in pnls if pnl > 0)
        pattern_id = hashlib.sha256(label.encode("utf-8")).hexdigest()[:16]
        sample = len(metrics)
        win_rate = wins / sample if sample else 0.0
        p_value = math.erfc(abs((win_rate - 0.5) / math.sqrt(0.25 / sample)) / math.sqrt(2)) if sample else 1.0
        return {
            "pattern_id": pattern_id,
            "label": label,
            "sample_size": sample,
            "win_rate_pct": round(win_rate * 100, 2),
            "expectancy": self._mean(pnls),
            "mae_pct": self._mean([metric["mae_pct"] for metric in metrics]),
            "mfe_pct": self._mean([metric["mfe_pct"] for metric in metrics]),
            "average_hold_minutes": self._mean([metric["hold_minutes"] for metric in metrics]),
            "risk_adjusted_return": self._mean([metric["risk_adjusted_return"] for metric in metrics]),
            "confidence_level": "HIGH" if sample >= self.HIGH_CONFIDENCE_SAMPLE_SIZE and p_value < 0.05 else "MEDIUM" if sample >= self.MIN_SAMPLE_SIZE else "LOW",
            "p_value": round(p_value, 5),
            "statistically_significant": bool(sample >= self.MIN_SAMPLE_SIZE and p_value < 0.05),
        }

    @staticmethod
    def _actual_metrics(bundle: Dict[str, Any]) -> Dict[str, float]:
        actual = ((bundle.get("alternative_outcomes") or {}).get("actual") or {})
        return {key: float(actual.get(key) or 0.0) for key in ("pnl", "mae_pct", "mfe_pct", "hold_minutes", "risk_adjusted_return")}

    @staticmethod
    def _trend(current: Dict[str, Any], previous: Dict[str, Any] | None) -> str:
        if previous is None:
            return "NEW"
        change = current["expectancy"] - float(previous.get("expectancy") or 0)
        if previous.get("expectancy", 0) > 0 and current["expectancy"] <= 0:
            return "FAILING_PREVIOUSLY_PROFITABLE"
        if change > 0.05:
            return "IMPROVING"
        if change < -0.05:
            return "DEGRADING"
        return "STABLE"

    @staticmethod
    def _advisory_status(pattern: Dict[str, Any]) -> str:
        if pattern["trend"] == "FAILING_PREVIOUSLY_PROFITABLE":
            return "Flag: previously profitable pattern is failing"
        if pattern["sample_size"] >= 20 and pattern["expectancy"] > 0 and pattern["statistically_significant"]:
            return "High-performing candidate for Rule Validation"
        if pattern["expectancy"] < 0 and pattern["statistically_significant"]:
            return "Underperforming pattern: investigate"
        return "Advisory evidence accumulating"

    def _append_if_changed(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        prior = self._latest_snapshot()
        comparable = {key: value for key, value in snapshot.items() if key not in {"created_at", "snapshot_hash", "previous_snapshot_hash"}}
        if prior:
            old = {key: value for key, value in prior.items() if key not in {"created_at", "snapshot_hash", "previous_snapshot_hash"}}
            if old == comparable:
                return prior
        self.data_dir.mkdir(parents=True, exist_ok=True)
        immutable = {**snapshot, "previous_snapshot_hash": (prior or {}).get("snapshot_hash", "")}
        immutable["snapshot_hash"] = hashlib.sha256(json.dumps(immutable, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(immutable, sort_keys=True) + "\n")
        return immutable

    def _latest_snapshot(self) -> Dict[str, Any] | None:
        if not self.history_path.exists():
            return None
        for line in reversed(self.history_path.read_text(encoding="utf-8").splitlines()):
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    return record
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _mean(values: List[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    @staticmethod
    def _bucket(value: float | None, bounds: tuple, labels: tuple) -> str:
        if value is None:
            return "UNKNOWN"
        for bound, label in zip(bounds, labels):
            if value < bound:
                return label
        return labels[-1]

    @staticmethod
    def _option_direction(symbol: Any) -> str:
        text = str(symbol or "").upper()
        return "PUT" if "P" in text[-12:] else "CALL"

    @staticmethod
    def _option_characteristics(trade: Dict[str, Any]) -> str:
        symbol = str(trade.get("option_symbol") or "").upper()
        direction = PatternDiscoveryEngine._option_direction(symbol)
        entry = PatternDiscoveryEngine._number(trade.get("option_entry_price"))
        price_band = "UNKNOWN_PREMIUM" if entry is None else "LOW_PREMIUM" if entry < 1 else "MID_PREMIUM" if entry < 3 else "HIGH_PREMIUM"
        return f"{direction}_{price_band}"

    @staticmethod
    def _volatility_bucket(candles: List[Dict[str, Any]]) -> str:
        if not candles:
            return "UNKNOWN"
        ranges = [(float(row["high"]) - float(row["low"])) / max(float(row["close"]), 0.01) for row in candles]
        average = sum(ranges) / len(ranges)
        return "HIGH" if average >= 0.0015 else "NORMAL" if average >= 0.0007 else "LOW"

    @staticmethod
    def _opening_range_behavior(candles: List[Dict[str, Any]]) -> str:
        if len(candles) < 2:
            return "UNKNOWN"
        first = candles[0]
        return "UP" if float(first["close"]) >= float(first["open"]) else "DOWN"

    @staticmethod
    def _time_bucket(value: Any) -> str:
        try:
            hour = datetime.fromisoformat(str(value).replace("Z", "+00:00")).hour
        except ValueError:
            return "UNKNOWN"
        return "OPENING" if hour < 15 else "MIDDAY" if hour < 18 else "CLOSING"
