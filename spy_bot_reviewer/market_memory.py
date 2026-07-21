"""Immutable market-context memory and deterministic historical analog retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class MarketMemoryEngine:
    """Advisory market memory; it has no live-bot or Rule Validation writes."""

    VERSION = "market-memory.v1"
    FEATURE_SCHEMA_VERSION = "market-context-features.v1"
    SIMILARITY_MODEL_VERSION = "cosine-pre-entry-v1"
    RETRIEVAL_ALGORITHM_VERSION = "sqlite-vector-scan-v1"

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.history_path = data_dir / "market_memory_history.jsonl"
        self.db_path = data_dir / "market_memory.sqlite"

    def capture_session(self, trading_date: str, bundles: Iterable[Dict[str, Any]], hypothesis_ids: Iterable[str] = ()) -> Dict[str, Any]:
        session_bundles = [bundle for bundle in bundles if self._trade_date(bundle) == trading_date]
        contexts = [self._trade_context(bundle) for bundle in session_bundles]
        if not contexts:
            return {"available": False, "trading_date": trading_date, "analogs": []}
        record = {
            "schema_version": self.VERSION,
            "feature_schema_version": self.FEATURE_SCHEMA_VERSION,
            "similarity_model_version": self.SIMILARITY_MODEL_VERSION,
            "retrieval_algorithm_version": self.RETRIEVAL_ALGORITHM_VERSION,
            "market_memory_id": f"market-memory-{trading_date}-{hashlib.sha256(json.dumps(contexts, sort_keys=True, default=str).encode()).hexdigest()[:12]}",
            "trading_date": trading_date,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "session_context": self._session_context(contexts, trading_date),
            "trade_contexts": contexts,
            "active_hypothesis_ids": sorted(set(hypothesis_ids)),
            "advisory_only": True,
        }
        record["vector"] = self._vector(record["session_context"])
        record = self._store(record)
        record["analogs"] = self.retrieve(record, exclude_trading_date=trading_date)
        return record

    def retrieve(self, query_record: Dict[str, Any], exclude_trading_date: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        self._initialize_db()
        query_vector = query_record.get("vector") or self._vector(query_record.get("session_context") or {})
        rows = []
        with sqlite3.connect(self.db_path) as connection:
            for memory_id, trading_date, record_json, vector_json in connection.execute("SELECT memory_id, trading_date, record_json, vector_json FROM market_memory_records"):
                if trading_date == exclude_trading_date:
                    continue
                record = json.loads(record_json)
                similarity = self._cosine(query_vector, json.loads(vector_json))
                rows.append((similarity, record))
        results = []
        for similarity, record in sorted(rows, key=lambda item: item[0], reverse=True)[:limit]:
            context = record.get("session_context") or {}
            results.append({
                "market_memory_id": record.get("market_memory_id"),
                "trading_date": record.get("trading_date"),
                "similarity_score": round(similarity, 4),
                "similarity_reasons": self._similarity_reasons(query_record.get("session_context") or {}, context),
                "outcomes": self._outcome_summary(record),
                "active_hypothesis_ids": record.get("active_hypothesis_ids") or [],
                "pattern_outcomes": self._pattern_outcomes(record),
                "counterfactual_conclusions": self._counterfactual_conclusions(record),
                "advisory_only": True,
            })
        return results

    def latest_for_date(self, trading_date: str) -> Optional[Dict[str, Any]]:
        records = self._history()
        for record in reversed(records):
            if record.get("trading_date") == trading_date:
                record["analogs"] = self.retrieve(record, exclude_trading_date=trading_date)
                return record
        return None

    def _trade_context(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        trade = bundle.get("trade") or {}
        entry_time = self._time(trade.get("entry_time"))
        exit_time = self._time(trade.get("exit_time"))
        candles = ((bundle.get("candles") or {}).get("1m") or [])
        pre = [row for row in candles if entry_time and self._time(row.get("time")) <= entry_time]
        during = [row for row in candles if entry_time and exit_time and entry_time <= self._time(row.get("time")) <= exit_time]
        post = [row for row in candles if exit_time and self._time(row.get("time")) > exit_time]
        features = self._features(pre, trade, bundle.get("execution") or {})
        actual = ((bundle.get("alternative_outcomes") or {}).get("actual") or {})
        return {"trade_id": str(bundle.get("trade_id") or trade.get("trade_id") or ""), "entry_time": trade.get("entry_time"), "exit_time": trade.get("exit_time"), "pre_trade_features": features, "before": self._price_structure(pre), "during": self._price_structure(during), "after": self._price_structure(post), "outcome": actual, "counterfactual": bundle.get("alternative_outcomes") or {}, "market_events": bundle.get("market_events") or [], "evidence_gaps": bundle.get("evidence_gaps") or []}

    def _session_context(self, contexts: List[Dict[str, Any]], trading_date: str) -> Dict[str, Any]:
        features = contexts[0]["pre_trade_features"]
        parsed = datetime.fromisoformat(trading_date)
        return {**features, "trading_date": trading_date, "day_of_week": parsed.strftime("%A"), "month": parsed.month, "season": self._season(parsed.month), "options_expiration_proximity_days": (4 - parsed.weekday()) % 7, "trade_count": len(contexts), "economic_events": [event for context in contexts for event in context.get("market_events") or []]}

    def _features(self, candles: List[Dict[str, Any]], trade: Dict[str, Any], execution: Dict[str, Any]) -> Dict[str, Any]:
        last = candles[-1] if candles else {}
        first = candles[0] if candles else {}
        closes = [float(row.get("close") or 0) for row in candles]
        returns = [(closes[index] - closes[index - 1]) / max(abs(closes[index - 1]), .01) for index in range(1, len(closes))]
        realized_vol = math.sqrt(sum(value * value for value in returns) / len(returns)) if returns else None
        high = max((float(row.get("high") or 0) for row in candles), default=0)
        low = min((float(row.get("low") or 0) for row in candles), default=0)
        close = float(last.get("close") or 0)
        atr = sum(float(row.get("high") or 0) - float(row.get("low") or 0) for row in candles[-14:]) / min(len(candles), 14) if candles else None
        return {
            "realized_volatility": realized_vol,
            "implied_volatility": execution.get("implied_volatility"),
            "vix": execution.get("vix"),
            "breadth": execution.get("breadth"),
            "opening_gap_pct": ((float(first.get("close") or 0) - float(first.get("open") or 0)) / max(abs(float(first.get("open") or 1)), .01)) if first else None,
            "opening_range_pct": (high - low) / max(abs(close), .01) if candles else None,
            "volume_profile": "HIGH" if sum(float(row.get("volume") or 0) for row in candles) >= 50000 else "LOW",
            "trend_state": "UP" if float(last.get("ema10") or 0) >= float(last.get("ema20") or 0) else "DOWN",
            "ema_relationship": "BULLISH" if float(last.get("ema10") or 0) >= float(last.get("ema20") or 0) else "BEARISH",
            "vwap_behavior": "ABOVE" if float(last.get("close") or 0) >= float(last.get("vwap") or 0) else "BELOW",
            "rsi": last.get("rsi"), "macd": last.get("macd"), "atr": atr,
            "market_regime": trade.get("market_regime"), "confidence_score": execution.get("confidence_score") or trade.get("entry_score"),
        }

    def _vector(self, features: Dict[str, Any]) -> List[float]:
        return [self._number(features.get(key)) for key in ("realized_volatility", "opening_gap_pct", "opening_range_pct", "rsi", "macd", "atr", "confidence_score")] + [1.0 if features.get("trend_state") == "UP" else -1.0, 1.0 if features.get("vwap_behavior") == "ABOVE" else -1.0]

    def _store(self, record: Dict[str, Any]) -> Dict[str, Any]:
        prior = self.latest_for_date(record["trading_date"])
        record["previous_record_hash"] = (prior or {}).get("record_hash", "")
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
        record["record_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        self._initialize_db()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("INSERT OR REPLACE INTO market_memory_records (memory_id, trading_date, record_json, vector_json) VALUES (?, ?, ?, ?)", (record["market_memory_id"], record["trading_date"], json.dumps(record, sort_keys=True, default=str), json.dumps(record["vector"])))
        return record

    def _initialize_db(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS market_memory_records (memory_id TEXT PRIMARY KEY, trading_date TEXT NOT NULL, record_json TEXT NOT NULL, vector_json TEXT NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_market_memory_date ON market_memory_records(trading_date)")

    def _history(self) -> List[Dict[str, Any]]:
        if not self.history_path.exists(): return []
        records = []
        for line in self.history_path.read_text(encoding="utf-8").splitlines():
            try: records.append(json.loads(line))
            except json.JSONDecodeError: continue
        return records

    @staticmethod
    def _price_structure(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not candles: return {"available": False}
        return {"available": True, "open": candles[0].get("open"), "high": max(float(row.get("high") or 0) for row in candles), "low": min(float(row.get("low") or 0) for row in candles), "close": candles[-1].get("close"), "volume": sum(float(row.get("volume") or 0) for row in candles)}

    @staticmethod
    def _outcome_summary(record: Dict[str, Any]) -> Dict[str, Any]:
        outcomes = [context.get("outcome") or {} for context in record.get("trade_contexts") or []]
        return {"trade_count": len(outcomes), "pnl": round(sum(float(item.get("pnl") or 0) for item in outcomes), 4), "win_rate_pct": round(sum(1 for item in outcomes if float(item.get("pnl") or 0) > 0) / len(outcomes) * 100, 2) if outcomes else 0.0}

    @staticmethod
    def _pattern_outcomes(record: Dict[str, Any]) -> List[str]:
        context = record.get("session_context") or {}
        return [f"regime={context.get('market_regime')}", f"trend={context.get('trend_state')}", f"VWAP={context.get('vwap_behavior')}"]

    @staticmethod
    def _counterfactual_conclusions(record: Dict[str, Any]) -> List[str]:
        results = []
        for context in record.get("trade_contexts") or []:
            for alternative in (context.get("counterfactual") or {}).get("alternatives") or []:
                if float(alternative.get("delta_pnl") or 0) > 0: results.append(str(alternative.get("name")))
        return sorted(set(results))[:3]

    @staticmethod
    def _similarity_reasons(query: Dict[str, Any], candidate: Dict[str, Any]) -> List[str]:
        reasons = []
        for key in ("trend_state", "ema_relationship", "vwap_behavior", "market_regime", "day_of_week", "season"):
            if query.get(key) is not None and query.get(key) == candidate.get(key): reasons.append(f"same {key.replace('_', ' ')}")
        return reasons or ["closest available pre-entry feature vector"]

    @staticmethod
    def _cosine(left: List[float], right: List[float]) -> float:
        numerator = sum(a * b for a, b in zip(left, right)); denom = math.sqrt(sum(a*a for a in left)) * math.sqrt(sum(b*b for b in right)); return numerator / denom if denom else 0.0

    @staticmethod
    def _number(value: Any) -> float:
        try: return float(value or 0.0)
        except (TypeError, ValueError): return 0.0

    @staticmethod
    def _time(value: Any) -> Optional[datetime]:
        try: return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError: return None

    @staticmethod
    def _season(month: int) -> str:
        return "WINTER" if month in {12,1,2} else "SPRING" if month in {3,4,5} else "SUMMER" if month in {6,7,8} else "AUTUMN"

    @staticmethod
    def _trade_date(bundle: Dict[str, Any]) -> str:
        value = (bundle.get("trade") or {}).get("entry_time")
        return str(value)[:10] if value else ""
