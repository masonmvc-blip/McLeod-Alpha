"""Post-session SPY trade review and rule-validation service.

This package deliberately reads exported session artifacts and never imports or
mutates the live trading engine. Rule promotion creates an auditable decision;
applying a promoted rule remains a separate, explicit deployment concern.
"""

from __future__ import annotations

import hashlib
import json
import os
import csv
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .patterns import PatternDiscoveryEngine
from .hypotheses import HypothesisRegistry
from .market_memory import MarketMemoryEngine
from .governance import ResearchGovernanceEngine
from .experiments import ExperimentFramework


class SpyBotReviewer:
    """Collect session evidence, create immutable reviews, and validate rules."""

    SCHEMA_VERSION = "2.0"
    REVIEWER_VERSION = "trade-replay-learning-engine.v1"
    PROMPT_VERSION = "spy-review-prompt.v2"
    COUNTERFACTUAL_VERSION = "counterfactual-v1"
    COUNTERFACTUAL_MIN_SAMPLE_SIZE = 20

    def __init__(self, project_root: Path | str):
        self.root = Path(project_root)
        self.data_dir = self.root / "data" / "spy_bot_reviewer"
        self.history_path = self.data_dir / "review_history.jsonl"
        self.rules_path = self.data_dir / "rule_validation_history.jsonl"
        self.scheduler_state_path = self.data_dir / "scheduler_state.json"
        self.replay_dir = self.data_dir / "replays"

    def maybe_run_after_session(self, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """Run exactly once per weekday after the regular SPY options session."""
        if os.getenv("SPY_BOT_REVIEWER_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
            return None
        eastern = ZoneInfo("America/New_York")
        current = (now or datetime.now(eastern)).astimezone(eastern)
        if current.weekday() >= 5 or (current.hour, current.minute) < (16, 5):
            return None
        state = self._read_json(self.scheduler_state_path, {})
        trading_date = current.date().isoformat()
        if state.get("last_reviewed_date") == trading_date:
            return None
        from execution.daily_trade_log_email import generate_daily_trade_review_data

        export_path = generate_daily_trade_review_data(trading_date)
        review = self.run_session_review(trading_date, export_path)
        self.scheduler_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.scheduler_state_path.write_text(json.dumps({"last_reviewed_date": trading_date, "review_id": review["review_id"], "completed_at": datetime.now(timezone.utc).isoformat()}, sort_keys=True), encoding="utf-8")
        return review

    def run_session_review(self, trading_date: str, export_path: Optional[Path | str] = None) -> Dict[str, Any]:
        evidence = self.collect_session_evidence(trading_date, export_path)
        pattern_snapshot = PatternDiscoveryEngine(self.data_dir).discover(self._replay_bundles())
        analysis = self._analyze(evidence)
        self._register_recommendations(analysis)
        self._register_counterfactual_hypotheses()
        self._register_pattern_hypotheses(pattern_snapshot)
        HypothesisRegistry(self.data_dir).refresh_evidence(self._replay_bundles(), self.REVIEWER_VERSION)
        ExperimentFramework(self.data_dir).sync(
            HypothesisRegistry(self.data_dir).current(),
            self._replay_bundles(),
            {"strategy_version": "unknown", "feature_set": "replay-candles-v1", "reviewer_version": self.REVIEWER_VERSION, "prompt_version": self.PROMPT_VERSION, "market_memory_version": "market-memory.v1", "data_schema_version": self.SCHEMA_VERSION},
        )
        market_memory = MarketMemoryEngine(self.data_dir).capture_session(
            trading_date,
            self._replay_bundles(),
            HypothesisRegistry(self.data_dir).current().keys(),
        )
        governance = ResearchGovernanceEngine(self.data_dir).snapshot()
        record = {
            "schema_version": self.SCHEMA_VERSION,
            "reviewer_version": self.REVIEWER_VERSION,
            "prompt_version": self.PROMPT_VERSION,
            "model_version": analysis.get("model") or "deterministic-v1",
            "record_type": "session_review",
            "review_id": f"spy-review-{trading_date}-{datetime.now(timezone.utc).strftime('%H%M%S%f')}",
            "trading_date": trading_date,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "evidence": evidence,
            "pattern_discovery_snapshot_hash": pattern_snapshot.get("snapshot_hash"),
            "market_memory_id": market_memory.get("market_memory_id"),
            "market_memory_record_hash": market_memory.get("record_hash"),
            "historical_analogs": market_memory.get("analogs", []),
            "research_governance_snapshot_hash": governance.get("snapshot_hash"),
            "analysis": analysis,
        }
        return self._append_immutable(self.history_path, record)

    def collect_session_evidence(self, trading_date: str, export_path: Optional[Path | str] = None) -> Dict[str, Any]:
        source_path = Path(export_path) if export_path else self.root / "data" / "reports" / "trade_logs" / f"daily_trade_review_data_{trading_date}.json"
        exported = self._read_json(source_path, {"trades": [], "summary": {}})
        trades = exported.get("trades", []) if isinstance(exported, dict) else []
        spy_trades = [trade for trade in trades if self._is_spy_trade(trade)]
        replay_bundles = [self._capture_replay_bundle(trade) for trade in spy_trades]
        screenshots = self._artifact_paths(("*.png", "*.jpg", "*.jpeg", "*.webp"), trading_date)
        execution_logs = self._artifact_paths(("*.log", "*.jsonl"), trading_date, directories=(self.root / "logs", self.root / "data" / "reports"))
        bot_log = self._log_excerpt(trading_date)
        return {
            "export_path": str(source_path),
            "export_sha256": self._sha256_file(source_path),
            "session_summary": exported.get("summary", {}) if isinstance(exported, dict) else {},
            "trades": spy_trades,
            "replay_bundles": replay_bundles,
            "market_context": self._market_context(spy_trades),
            "screenshots": screenshots,
            "execution_logs": execution_logs,
            "bot_log_excerpt": bot_log,
        }

    def replay_bundle(self, trade_id: str) -> Optional[Dict[str, Any]]:
        """Return immutable evidence for one trade; never regenerate historical data."""
        safe_id = "".join(char for char in str(trade_id) if char.isalnum() or char in "-_")
        if not safe_id:
            return None
        return self._read_json(self.replay_dir / f"{safe_id}.json", None)

    def dashboard_payload(self, trading_date: Optional[str] = None) -> Dict[str, Any]:
        reviews = self._read_history(self.history_path)
        if trading_date:
            reviews = [review for review in reviews if review.get("trading_date") == trading_date]
        rules = self._read_history(self.rules_path)
        latest_date = (reviews[-1] if reviews else {}).get("trading_date")
        return {
            "available": bool(reviews),
            "latest_review": reviews[-1] if reviews else None,
            "review_history": list(reversed(reviews[-20:])),
            "rule_validations": list(reversed(rules[-50:])),
            "counterfactual_summary": self.counterfactual_summary(),
            "pattern_discovery": PatternDiscoveryEngine(self.data_dir).latest(),
            "hypotheses": HypothesisRegistry(self.data_dir).ranked(),
            "market_memory": MarketMemoryEngine(self.data_dir).latest_for_date(latest_date) if latest_date else None,
            "research_governance": ResearchGovernanceEngine(self.data_dir).latest(),
            "experiments": ExperimentFramework(self.data_dir).ranked(),
            "promotion_policy": {"minimum_sample_size": 20, "minimum_expectancy_improvement": 0.0, "requires_positive_candidate_expectancy": True, "automatic_live_deployment": False},
        }

    def _replay_bundles(self) -> List[Dict[str, Any]]:
        if not self.replay_dir.exists():
            return []
        return [bundle for bundle in (self._read_json(path, {}) for path in sorted(self.replay_dir.glob("*.json"))) if isinstance(bundle, dict) and bundle.get("trade")]

    def validate_rule(self, rule_id: str, proposal: str, trade_outcomes: Iterable[Dict[str, Any]], minimum_sample_size: int = 20) -> Dict[str, Any]:
        outcomes = list(trade_outcomes)
        baseline = [self._pnl(row) for row in outcomes]
        candidate = [self._pnl(row) for row in outcomes if bool(row.get("rule_eligible"))]
        baseline_expectancy = self._mean(baseline)
        candidate_expectancy = self._mean(candidate)
        improvement = candidate_expectancy - baseline_expectancy
        statistically_meaningful = len(candidate) >= minimum_sample_size
        validated = statistically_meaningful and candidate_expectancy > 0 and improvement > 0
        record = {
            "schema_version": self.SCHEMA_VERSION,
            "record_type": "rule_validation",
            "rule_id": rule_id,
            "proposal": proposal,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sample_size": len(candidate),
            "baseline_sample_size": len(baseline),
            "baseline_expectancy": baseline_expectancy,
            "candidate_expectancy": candidate_expectancy,
            "expectancy_improvement": improvement,
            "status": "Validated" if validated else ("Rejected" if statistically_meaningful else "Testing"),
            "trades_tested": len(candidate),
            "statistically_meaningful": statistically_meaningful,
            "promotion": {"automatic_live_deployment": False, "requires_manual_approval": True},
        }
        return self._append_immutable(self.rules_path, record)

    def _register_recommendations(self, analysis: Dict[str, Any]) -> None:
        structured = analysis.get("structured_review") or {}
        recommendations = structured.get("proposed_rules") if isinstance(structured, dict) else []
        for recommendation in recommendations or []:
            proposal = recommendation if isinstance(recommendation, str) else json.dumps(recommendation, sort_keys=True)
            HypothesisRegistry(self.data_dir).ingest(
                source="trade_replay_ai",
                proposal=proposal,
                originating_evidence={"analysis_provider": analysis.get("provider"), "model": analysis.get("model")},
                reviewer_version=self.REVIEWER_VERSION,
            )

    def _register_counterfactual_hypotheses(self) -> None:
        registry = HypothesisRegistry(self.data_dir)
        for improvement in self.counterfactual_summary().get("improvements", []):
            if float(improvement.get("expectancy_improvement") or 0) <= 0:
                continue
            registry.ingest(
                source="counterfactual_analyzer",
                proposal=f"Evaluate {improvement['name']} as a strategy rule.",
                originating_evidence=improvement,
                expected_improvement=float(improvement.get("expectancy_improvement") or 0),
                supporting_trade_ids=[],
                reviewer_version=self.REVIEWER_VERSION,
            )

    def _register_pattern_hypotheses(self, snapshot: Dict[str, Any]) -> None:
        registry = HypothesisRegistry(self.data_dir)
        for pattern in snapshot.get("patterns", []):
            if pattern.get("advisory_status") != "High-performing candidate for Rule Validation":
                continue
            registry.ingest(
                source="pattern_discovery",
                proposal=f"Evaluate pattern guard: {pattern['label']}.",
                originating_evidence=pattern,
                expected_improvement=float(pattern.get("expectancy") or 0),
                minimum_sample_size=max(20, int(pattern.get("sample_size") or 0)),
                reviewer_version=self.REVIEWER_VERSION,
            )

    def promote_hypothesis_to_rule_validation(self, hypothesis_id: str) -> Dict[str, Any]:
        """Manual-only bridge; this never modifies live trading configuration."""
        registry = HypothesisRegistry(self.data_dir)
        if not ExperimentFramework(self.data_dir).eligible_for_manual_promotion(hypothesis_id):
            raise ValueError("a concluded successful experiment is required before Rule Validation promotion")
        hypothesis = registry.manual_promote(hypothesis_id, self.REVIEWER_VERSION)
        outcomes = [{"pnl": ((bundle.get("alternative_outcomes") or {}).get("actual") or {}).get("pnl", 0), "rule_eligible": str((bundle.get("trade") or {}).get("trade_id") or bundle.get("trade_id")) in set(hypothesis.get("supporting_trade_ids") or [])} for bundle in self._replay_bundles()]
        validation = self.validate_rule(hypothesis_id, hypothesis["proposal"], outcomes, int(hypothesis.get("minimum_sample_size") or 20))
        return {"hypothesis": hypothesis, "rule_validation": validation, "automatic_live_deployment": False}

    def _capture_replay_bundle(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        trade_id = str(trade.get("trade_id") or hashlib.sha256(json.dumps(trade, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16])
        safe_id = "".join(char for char in trade_id if char.isalnum() or char in "-_")
        path = self.replay_dir / f"{safe_id}.json"
        existing = self._read_json(path, None)
        if isinstance(existing, dict):
            return {"trade_id": trade_id, "replay_path": str(path.relative_to(self.root)), "replay_sha256": self._sha256_file(path), "reused": True}
        entry = self._parse_time(trade.get("entry_time"))
        exit_time = self._parse_time(trade.get("exit_time")) or entry
        start = entry - timedelta(minutes=60) if entry else None
        end = exit_time + timedelta(minutes=30) if exit_time else None
        candles_1m = self._load_windowed_candles(start, end)
        self.replay_dir.mkdir(parents=True, exist_ok=True)
        chart_snapshots = self._write_chart_snapshots(safe_id, candles_1m, entry, exit_time)
        bundle = {
            "schema_version": self.SCHEMA_VERSION,
            "reviewer_version": self.REVIEWER_VERSION,
            "trade_id": trade_id,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "trade": trade,
            "window": {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None, "minimum_required": "60m before entry through 30m after exit"},
            "candles": {"1m": candles_1m, "5m": self._resample(candles_1m, 5), "15m": self._resample(candles_1m, 15), "source": "data/spy_1min_history.csv"},
            "execution": self._execution_evidence(trade),
            "screenshots": self._screenshots_for_trade(trade) + chart_snapshots,
            "market_events": self._market_events(trade),
            "evidence_gaps": [],
        }
        bundle["scores"] = self._objective_scores(bundle)
        bundle["alternative_outcomes"] = self._counterfactual_outcomes(bundle)
        if not candles_1m:
            bundle["evidence_gaps"].append("No archived 1-minute candles were available; historical replay cannot be exact.")
        for field in ("option_chain_snapshot", "bid_ask_spread", "fill_details", "strategy_version", "confidence_score", "vix"):
            if bundle["execution"].get(field) in (None, "", {}, []):
                bundle["evidence_gaps"].append(f"Missing persisted {field.replace('_', ' ')}.")
        immutable = {**bundle, "previous_bundle_hash": self._latest_bundle_hash()}
        immutable["bundle_hash"] = hashlib.sha256(json.dumps(immutable, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
        path.write_text(json.dumps(immutable, sort_keys=True, default=str), encoding="utf-8")
        return {"trade_id": trade_id, "replay_path": str(path.relative_to(self.root)), "replay_sha256": self._sha256_file(path), "reused": False, "scores": immutable["scores"]}

    def counterfactual_summary(self) -> Dict[str, Any]:
        """Aggregate immutable replay results; never promote a strategy change."""
        candidates: Dict[str, List[float]] = {}
        baseline: List[float] = []
        for path in sorted(self.replay_dir.glob("*.json")) if self.replay_dir.exists() else []:
            bundle = self._read_json(path, {})
            analysis = bundle.get("alternative_outcomes") or {}
            actual = (analysis.get("actual") or {}).get("pnl")
            if actual is not None:
                baseline.append(float(actual))
            for result in analysis.get("alternatives") or []:
                if result.get("comparison") != "alternative":
                    continue
                candidates.setdefault(str(result.get("name")), []).append(float(result.get("pnl") or 0))
        baseline_expectancy = self._mean(baseline)
        improvements = []
        for name, pnls in sorted(candidates.items()):
            improvement = self._mean(pnls) - baseline_expectancy
            meaningful = len(pnls) >= self.COUNTERFACTUAL_MIN_SAMPLE_SIZE
            improvements.append({"name": name, "trades_tested": len(pnls), "expectancy": self._mean(pnls), "expectancy_improvement": round(improvement, 4), "status": "Candidate for Rule Validation" if meaningful and improvement > 0 else "Collecting evidence", "manual_approval_required": True, "automatic_live_deployment": False})
        return {"counterfactual_version": self.COUNTERFACTUAL_VERSION, "baseline_expectancy": baseline_expectancy, "minimum_sample_size": self.COUNTERFACTUAL_MIN_SAMPLE_SIZE, "improvements": improvements}

    def _counterfactual_outcomes(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        candles = bundle["candles"]["1m"]
        trade = bundle["trade"]
        entry_time = self._parse_time(trade.get("entry_time"))
        exit_time = self._parse_time(trade.get("exit_time"))
        if not candles or not entry_time or not exit_time:
            return {"version": self.COUNTERFACTUAL_VERSION, "method": "No simulation without archived candle evidence.", "actual": {}, "alternatives": []}
        entry_index = self._candle_index(candles, entry_time)
        exit_index = self._candle_index(candles, exit_time)
        direction = 1 if str(trade.get("direction") or "CALL").upper() != "PUT" else -1
        actual = self._simulate_path("Actual trade", candles, entry_index, exit_index, direction, "recorded_exit")
        alternatives = [
            self._simulate_path("Enter 1 candle earlier", candles, max(0, entry_index - 1), exit_index, direction, "recorded_exit"),
            self._simulate_path("Enter 2 candles earlier", candles, max(0, entry_index - 2), exit_index, direction, "recorded_exit"),
            self._simulate_path("Enter 1 candle later", candles, min(len(candles) - 1, entry_index + 1), exit_index, direction, "recorded_exit"),
            self._simulate_path("Enter 2 candles later", candles, min(len(candles) - 1, entry_index + 2), exit_index, direction, "recorded_exit"),
            self._simulate_path("Wait for two-candle confirmation", candles, min(len(candles) - 1, entry_index + 2), None, direction, "ema20_cross"),
            self._simulate_path("Technical EMA20 exit", candles, entry_index, None, direction, "ema20_cross"),
            self._simulate_path("0.25% protective stop", candles, entry_index, None, direction, "stop", stop_pct=0.0025),
            self._simulate_path("0.50% profit target", candles, entry_index, None, direction, "target", target_pct=0.005),
            {"name": "Skip trade", "comparison": "alternative", "decision": "skip", "pnl": 0.0, "expectancy_contribution": 0.0, "mae_pct": 0.0, "mfe_pct": 0.0, "drawdown_pct": 0.0, "hold_minutes": 0, "risk_adjusted_return": 0.0, "information_policy": "No trade; no future data used."},
        ]
        for alternative in alternatives:
            alternative["delta_pnl"] = round(float(alternative.get("pnl") or 0) - float(actual.get("pnl") or 0), 4)
        return {"version": self.COUNTERFACTUAL_VERSION, "information_policy": "Signals are evaluated candle-by-candle using only candles at or before each decision. Future candles are used solely to realize the chosen rule's outcome.", "actual": actual, "alternatives": alternatives}

    def _simulate_path(self, name: str, candles: List[Dict[str, Any]], entry_index: int, fixed_exit_index: Optional[int], direction: int, exit_rule: str, stop_pct: Optional[float] = None, target_pct: Optional[float] = None) -> Dict[str, Any]:
        entry_index = max(0, min(entry_index, len(candles) - 1))
        entry_price = float(candles[entry_index]["close"])
        exit_index = len(candles) - 1 if fixed_exit_index is None else max(entry_index, min(fixed_exit_index, len(candles) - 1))
        for index in range(entry_index + 1, exit_index + 1):
            # Each predicate reads only the current candle and its already-calculated indicators.
            candle = candles[index]; current_return = direction * (float(candle["close"]) - entry_price) / entry_price
            technical_exit = exit_rule == "ema20_cross" and ((direction > 0 and candle.get("close", 0) < candle.get("ema20", float("inf"))) or (direction < 0 and candle.get("close", 0) > candle.get("ema20", float("-inf"))))
            if (stop_pct is not None and current_return <= -stop_pct) or (target_pct is not None and current_return >= target_pct) or technical_exit:
                exit_index = index
                break
        returns = [direction * (float(candle["close"]) - entry_price) / entry_price for candle in candles[entry_index:exit_index + 1]]
        pnl = round(returns[-1] * 1000, 4) if returns else 0.0
        peak = max(returns) if returns else 0.0
        drawdown = min((value - max(returns[:index + 1]) for index, value in enumerate(returns)), default=0.0)
        return {"name": name, "comparison": "actual" if name == "Actual trade" else "alternative", "entry_time": candles[entry_index]["time"], "exit_time": candles[exit_index]["time"], "exit_rule": exit_rule, "pnl": pnl, "expectancy_contribution": pnl, "mae_pct": round(abs(min(0.0, min(returns, default=0.0))) * 100, 4), "mfe_pct": round(max(0.0, peak) * 100, 4), "drawdown_pct": round(abs(drawdown) * 100, 4), "hold_minutes": exit_index - entry_index, "risk_adjusted_return": round((returns[-1] / max(abs(min(returns, default=0.0)), 0.0001)), 4) if returns else 0.0, "pnl_basis": "SPY-underlying proxy at $1,000 notional; option-specific historical marks were not available.", "information_policy": "No look-ahead signal evaluation."}

    @staticmethod
    def _candle_index(candles: List[Dict[str, Any]], target: datetime) -> int:
        return min(range(len(candles)), key=lambda index: abs((SpyBotReviewer._parse_time(candles[index]["time"]) - target).total_seconds()))

    def _load_windowed_candles(self, start: Optional[datetime], end: Optional[datetime]) -> List[Dict[str, Any]]:
        path = self.root / "data" / "spy_1min_history.csv"
        if not path.exists() or not start or not end:
            return []
        rows: List[Dict[str, Any]] = []
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                timestamp = self._parse_time(row.get("datetime") or row.get("timestamp"))
                if timestamp is None or timestamp < start or timestamp > end:
                    continue
                try:
                    candle = {"time": timestamp.isoformat(), **{key: round(float(row[key]), 6) for key in ("open", "high", "low", "close", "volume") if row.get(key) not in (None, "")}}
                except (TypeError, ValueError):
                    continue
                rows.append(candle)
        return self._with_indicators(sorted(rows, key=lambda row: row["time"]))

    @staticmethod
    def _resample(candles: List[Dict[str, Any]], minutes: int) -> List[Dict[str, Any]]:
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for candle in candles:
            timestamp = datetime.fromisoformat(candle["time"].replace("Z", "+00:00"))
            minute = timestamp.minute - (timestamp.minute % minutes)
            key = timestamp.replace(minute=minute, second=0, microsecond=0).isoformat()
            buckets.setdefault(key, []).append(candle)
        return [{"time": key, "open": group[0]["open"], "high": max(row["high"] for row in group), "low": min(row["low"] for row in group), "close": group[-1]["close"], "volume": sum(row.get("volume", 0) for row in group)} for key, group in sorted(buckets.items())]

    @staticmethod
    def _with_indicators(candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ema10 = ema20 = ema26 = ema12 = None
        gains: List[float] = []; losses: List[float] = []; cumulative_pv = cumulative_volume = 0.0; prior = None
        for candle in candles:
            close = candle["close"]; volume = candle.get("volume", 0.0)
            ema10 = close if ema10 is None else close * 2 / 11 + ema10 * 9 / 11
            ema20 = close if ema20 is None else close * 2 / 21 + ema20 * 19 / 21
            ema12 = close if ema12 is None else close * 2 / 13 + ema12 * 11 / 13
            ema26 = close if ema26 is None else close * 2 / 27 + ema26 * 25 / 27
            typical = (candle["high"] + candle["low"] + close) / 3; cumulative_pv += typical * volume; cumulative_volume += volume
            if prior is not None:
                gains.append(max(0.0, close - prior)); losses.append(max(0.0, prior - close))
            prior = close; avg_gain = sum(gains[-14:]) / min(len(gains), 14) if gains else 0; avg_loss = sum(losses[-14:]) / min(len(losses), 14) if losses else 0
            candle.update({"ema10": round(ema10, 6), "ema20": round(ema20, 6), "vwap": round(cumulative_pv / cumulative_volume, 6) if cumulative_volume else None, "macd": round(ema12 - ema26, 6), "rsi": round(100 if avg_loss == 0 and avg_gain else 100 - 100 / (1 + avg_gain / avg_loss), 4) if (avg_gain or avg_loss) else 50.0})
        return candles

    def _execution_evidence(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        evidence: Dict[str, Any] = {"entry_order_id": trade.get("broker_entry_order_id"), "exit_order_id": trade.get("broker_exit_order_id"), "option_symbol": trade.get("option_symbol"), "entry_price": trade.get("option_entry_price"), "exit_price": trade.get("option_exit_price"), "option_chain_snapshot": None, "bid_ask_spread": None, "fill_details": None, "strategy_version": None, "confidence_score": trade.get("entry_score"), "vix": None, "diagnostic_snapshots": []}
        db_path = self.root / "data" / "mcleod_alpha.db"
        trade_id = trade.get("trade_id")
        if not db_path.exists() or trade_id is None:
            return evidence
        try:
            with sqlite3.connect(db_path) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute("SELECT feature_payload, entry_diagnostic_snapshot, exit_diagnostic_snapshot FROM trade_log WHERE id = ?", (trade_id,)).fetchone()
                if row:
                    for raw in row:
                        snapshot = self._json_object(raw)
                        if snapshot:
                            evidence["diagnostic_snapshots"].append(snapshot)
                            for key in ("option_chain_snapshot", "bid_ask_spread", "fill_details", "strategy_version", "confidence_score", "vix"):
                                if evidence.get(key) is None and snapshot.get(key) is not None:
                                    evidence[key] = snapshot[key]
        except sqlite3.Error:
            pass
        return evidence

    def _screenshots_for_trade(self, trade: Dict[str, Any]) -> List[str]:
        entry = self._parse_time(trade.get("entry_time"))
        return self._artifact_paths(("*.png", "*.jpg", "*.jpeg", "*.webp"), entry.date().isoformat() if entry else "")

    def _write_chart_snapshots(self, trade_id: str, candles: List[Dict[str, Any]], entry: Optional[datetime], exit_time: Optional[datetime]) -> List[str]:
        if not candles:
            return []
        output = []
        for label, focus in (("entry", entry), ("exit", exit_time)):
            path = self.replay_dir / f"{trade_id}_{label}_chart.svg"
            if path.exists():
                output.append(str(path.relative_to(self.root)))
                continue
            closes = [float(row["close"]) for row in candles]
            low, high = min(closes), max(closes)
            span = max(high - low, 0.01)
            points = " ".join(f"{20 + index * 760 / max(1, len(closes) - 1):.1f},{180 - (price - low) * 140 / span:.1f}" for index, price in enumerate(closes))
            marker = ""
            if focus:
                matched = min(range(len(candles)), key=lambda index: abs((self._parse_time(candles[index]["time"]) - focus).total_seconds()))
                x = 20 + matched * 760 / max(1, len(closes) - 1)
                marker = f'<line x1="{x:.1f}" y1="20" x2="{x:.1f}" y2="180" stroke="#b34a21" stroke-width="2"/>'
            path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="220" viewBox="0 0 800 220"><rect width="800" height="220" fill="#ffffff"/><text x="20" y="18" font-family="sans-serif" font-size="12">SPY replay {label} snapshot</text><polyline fill="none" stroke="#087e8b" stroke-width="2" points="{points}"/>{marker}</svg>', encoding="utf-8")
            output.append(str(path.relative_to(self.root)))
        return output

    def _market_events(self, trade: Dict[str, Any]) -> List[Dict[str, Any]]:
        entry = self._parse_time(trade.get("entry_time"))
        if not entry:
            return []
        events = []
        for path in self._artifact_paths(("*.json", "*.jsonl"), entry.date().isoformat(), directories=(self.root / "data" / "reports",)):
            if "event" in path.lower() or "calendar" in path.lower():
                events.append({"source": path, "captured": True})
        return events

    def _objective_scores(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        trade = bundle["trade"]; execution = bundle["execution"]; candles = bundle["candles"]["1m"]
        entry_score = self._number(trade.get("entry_score")); pnl = self._pnl(trade)
        setup = min(100, 35 + (entry_score or 0) * 0.65 + min(20, len(candles) / 6))
        entry_timing = min(100, 50 + (10 if candles else 0) + (15 if execution.get("confidence_score") is not None else 0))
        exit_timing = 80 if pnl > 0 else 45 if trade.get("exit_reason") else 30
        risk = 85 if trade.get("exit_reason") else 45
        execution = 75 + (15 if execution.get("fill_details") else 0) - (10 if trade.get("operational_errors") else 0)
        return {"Setup Quality": round(setup, 1), "Entry Timing": round(entry_timing, 1), "Exit Timing": round(exit_timing, 1), "Risk Management": round(risk, 1), "Execution Quality": round(max(0, min(100, execution)), 1), "method": "deterministic-v1", "note": "Scores use only persisted evidence; missing evidence cannot improve a score."}

    def _latest_bundle_hash(self) -> str:
        if not self.replay_dir.exists():
            return ""
        hashes = [self._read_json(path, {}).get("bundle_hash", "") for path in sorted(self.replay_dir.glob("*.json"))]
        return next((value for value in reversed(hashes) if value), "")

    @staticmethod
    def _json_object(value: Any) -> Dict[str, Any]:
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _parse_time(value: Any) -> Optional[datetime]:
        if value in (None, ""):
            return None
        try:
            text = str(value).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(text)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except ValueError:
            try:
                return datetime.fromtimestamp(float(value) / (1000 if float(value) > 1e11 else 1), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                return None

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _analyze(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        fallback = self._deterministic_analysis(evidence)
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            return {**fallback, "provider": "deterministic_fallback", "openai_status": "not_configured"}
        payload = {
            "model": os.getenv("SPY_BOT_REVIEWER_OPENAI_MODEL", "gpt-4.1-mini"),
            "input": [{"role": "system", "content": [{"type": "input_text", "text": "You are a conservative SPY options trading reviewer. Return strict JSON with keys executive_summary, trade_reviews, proposed_rules, and risk_flags. Proposals must be testable and must not be deployed automatically."}]}, {"role": "user", "content": [{"type": "input_text", "text": json.dumps(evidence, default=str)}]}],
            "text": {"format": {"type": "json_object"}},
        }
        try:
            request = Request("https://api.openai.com/v1/responses", data=json.dumps(payload).encode("utf-8"), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=45) as response:
                body = json.loads(response.read().decode("utf-8"))
            text = body.get("output_text") or "{}"
            return {"provider": "openai", "model": payload["model"], "structured_review": json.loads(text), "fallback_metrics": fallback["metrics"]}
        except (URLError, ValueError, OSError, json.JSONDecodeError) as exc:
            return {**fallback, "provider": "deterministic_fallback", "openai_status": f"failed: {exc}"}

    def _deterministic_analysis(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        trades = evidence.get("trades") or []
        pnls = [self._pnl(trade) for trade in trades]
        wins = sum(1 for pnl in pnls if pnl > 0)
        return {"metrics": {"trade_count": len(trades), "net_pnl": round(sum(pnls), 2), "expectancy": self._mean(pnls), "win_rate_pct": round((wins / len(pnls) * 100) if pnls else 0, 2)}, "executive_summary": "OpenAI review is pending configuration; deterministic session metrics are recorded.", "proposed_rules": [], "risk_flags": ["No automatic rule deployment is permitted."]}

    def _append_immutable(self, path: Path, record: Dict[str, Any]) -> Dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        previous_hash = ""
        if path.exists():
            rows = self._read_history(path)
            if rows:
                previous_hash = str(rows[-1].get("record_hash") or "")
        immutable = {**record, "previous_record_hash": previous_hash}
        canonical = json.dumps(immutable, sort_keys=True, separators=(",", ":"), default=str)
        immutable["record_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(immutable, sort_keys=True, default=str) + "\n")
        return immutable

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def _read_history(path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except json.JSONDecodeError:
                continue
        return rows

    def _artifact_paths(self, patterns: Iterable[str], trading_date: str, directories: Optional[Iterable[Path]] = None) -> List[str]:
        roots = directories or (self.root / "data", self.root / "reports", self.root / "logs")
        paths = []
        for directory in roots:
            if not directory.exists():
                continue
            for pattern in patterns:
                paths.extend(str(path.relative_to(self.root)) for path in directory.rglob(pattern) if trading_date in path.name)
        return sorted(set(paths))

    def _log_excerpt(self, trading_date: str) -> List[str]:
        path = self.root / "bot_output.log"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        matched = [line[-1000:] for line in lines if trading_date in line]
        return matched[-200:]

    @staticmethod
    def _market_context(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {"market_regimes": sorted({str(row.get("market_regime")) for row in trades if row.get("market_regime")}), "indicators": [{key: row.get(key) for key in ("entry_score", "trend_stage", "continuation_quality", "momentum_freshness_score", "momentum_acceleration", "absorption_score")} for row in trades]}

    @staticmethod
    def _is_spy_trade(trade: Dict[str, Any]) -> bool:
        return "SPY" in str(trade.get("option_symbol") or trade.get("symbol") or "SPY").upper()

    @staticmethod
    def _pnl(row: Dict[str, Any]) -> float:
        for key in ("dollar_pnl", "option_pnl_dollars", "pnl"):
            value = row.get(key)
            if value in (None, ""):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    @staticmethod
    def _mean(values: Iterable[float]) -> float:
        values = list(values)
        return round(sum(values) / len(values), 4) if values else 0.0

    @staticmethod
    def _sha256_file(path: Path) -> Optional[str]:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None