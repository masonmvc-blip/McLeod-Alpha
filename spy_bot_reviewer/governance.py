"""Advisory-only research performance, lifecycle, and governance reporting."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


class ResearchGovernanceEngine:
    """Reads immutable research ledgers and emits immutable governance snapshots."""

    VERSION = "research-governance.v1"
    STALE_HYPOTHESIS_DAYS = 30
    SUBSYSTEMS = {
        "trade_replay_ai": "Trade Replay Engine",
        "counterfactual_analyzer": "Counterfactual Analyzer",
        "pattern_discovery": "Pattern Discovery",
        "hypothesis_lab": "Hypothesis Laboratory",
        "rule_validation": "Rule Validation",
        "market_memory": "Market Memory",
    }

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.snapshot_path = data_dir / "research_governance_history.jsonl"
        self.lifecycle_path = data_dir / "recommendation_lifecycle.jsonl"

    def snapshot(self) -> Dict[str, Any]:
        hypotheses = self._latest_by_key(self.data_dir / "hypothesis_history.jsonl", "hypothesis_id")
        validations = self._records(self.data_dir / "rule_validation_history.jsonl")
        memories = self._records(self.data_dir / "market_memory_history.jsonl")
        self._sync_lifecycles(hypotheses, validations)
        lifecycles = self._latest_by_key(self.lifecycle_path, "recommendation_id")
        subsystem_metrics = self._subsystem_metrics(hypotheses, validations, memories, lifecycles)
        payload = {
            "schema_version": self.VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "subsystem_versions": {
                "Trade Replay Engine": "trade-replay-learning-engine.v1",
                "Counterfactual Analyzer": "counterfactual-v1",
                "Pattern Discovery": "pattern-discovery.v1",
                "Hypothesis Laboratory": "hypothesis-lab.v1",
                "Rule Validation": "rule-validation.v1",
                "Market Memory": "market-memory.v1",
            },
            "subsystems": subsystem_metrics,
            "recommendation_lifecycles": sorted(lifecycles.values(), key=lambda row: row.get("created_at", ""), reverse=True),
            "dependency_graph": self._dependency_graph(hypotheses, validations),
            "health": self._health(hypotheses, validations),
            "trend": self._trend(),
            "advisory_only": True,
            "manual_approval_required": True,
        }
        return self._append_snapshot_if_changed(payload)

    def latest(self) -> Dict[str, Any]:
        records = self._records(self.snapshot_path)
        return records[-1] if records else self.snapshot()

    def _sync_lifecycles(self, hypotheses: Dict[str, Dict[str, Any]], validations: List[Dict[str, Any]]) -> None:
        validation_by_id = {str(row.get("rule_id")): row for row in validations}
        latest = self._latest_by_key(self.lifecycle_path, "recommendation_id")
        for hypothesis_id, hypothesis in hypotheses.items():
            validation = validation_by_id.get(hypothesis_id)
            lifecycle = {
                "schema_version": self.VERSION,
                "recommendation_id": hypothesis_id,
                "originating_subsystem": self.SUBSYSTEMS.get(hypothesis.get("source"), hypothesis.get("source", "Unknown")),
                "originating_source": hypothesis.get("source"),
                "proposal": hypothesis.get("proposal"),
                "hypothesis_status": hypothesis.get("status"),
                "advanced_through_hypothesis_lab": True,
                "advanced_through_rule_validation": validation is not None,
                "rule_validation_status": validation.get("status") if validation else None,
                "adopted": False,
                "adoption_status": "Not adopted; no manual adoption record exists.",
                "measured_impact_after_adoption": None,
                "expected_improvement": hypothesis.get("expected_improvement"),
                "reviewer_version": hypothesis.get("reviewer_version"),
                "supporting_trade_ids": hypothesis.get("supporting_trade_ids") or [],
                "conflicting_trade_ids": hypothesis.get("conflicting_trade_ids") or [],
            }
            prior = latest.get(hypothesis_id)
            comparable = {key: value for key, value in lifecycle.items() if key not in {"created_at", "previous_lifecycle_hash", "lifecycle_hash"}}
            old = {key: value for key, value in (prior or {}).items() if key not in {"created_at", "previous_lifecycle_hash", "lifecycle_hash"}}
            if prior is None or comparable != old:
                self._append_lifecycle(lifecycle, prior)

    def _subsystem_metrics(self, hypotheses: Dict[str, Dict[str, Any]], validations: List[Dict[str, Any]], memories: List[Dict[str, Any]], lifecycles: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows = []
        for source, label in self.SUBSYSTEMS.items():
            generated = [row for row in hypotheses.values() if row.get("source") == source]
            if source == "hypothesis_lab": generated = list(hypotheses.values())
            if source == "rule_validation": generated = validations
            if source == "market_memory": generated = memories
            validated = [row for row in generated if str(row.get("status") or row.get("rule_validation_status")) == "Validated"]
            rejected = [row for row in generated if str(row.get("status") or row.get("rule_validation_status")) == "Rejected"]
            evaluated = len(validated) + len(rejected)
            impacts = [float(row.get("expectancy_improvement") or 0) for row in generated if row.get("expectancy_improvement") is not None]
            conversion = sum(1 for row in generated if row.get("status") in {"Ready for Validation", "Validating", "Validated", "Rejected"})
            durations = [self._duration_days(row) for row in generated if row.get("status") in {"Validating", "Validated", "Rejected"}]
            lifecycle_count = sum(1 for row in lifecycles.values() if row.get("originating_source") == source)
            rows.append({
                "subsystem": label,
                "recommendations_generated": len(generated),
                "permanent_lifecycle_records": lifecycle_count,
                "precision": round(len(validated) / evaluated, 4) if evaluated else None,
                "recall": None,
                "recall_note": "Not applicable until a labeled universe of missed recommendations exists.",
                "hypothesis_conversion_rate": round(conversion / len(generated), 4) if generated else None,
                "validation_success_rate": round(len(validated) / evaluated, 4) if evaluated else None,
                "rejected_recommendation_rate": round(len(rejected) / len(generated), 4) if generated else None,
                "false_positive_rate": round(len(rejected) / evaluated, 4) if evaluated else None,
                "average_expectancy_improvement": round(sum(impacts) / len(impacts), 4) if impacts else None,
                "average_days_hypothesis_to_validation": round(sum(durations) / len(durations), 2) if durations else None,
                "cumulative_contribution_to_trading_performance": 0.0,
                "contribution_note": "No manual adoption impact records are available; contribution is intentionally not inferred.",
                "advisory_only": True,
            })
        return rows

    def _dependency_graph(self, hypotheses: Dict[str, Dict[str, Any]], validations: List[Dict[str, Any]]) -> Dict[str, Any]:
        nodes = [{"id": label, "type": "subsystem"} for label in self.SUBSYSTEMS.values()]
        edges = [
            {"from": "Trade Replay Engine", "to": "Hypothesis Laboratory", "type": "recommendation"},
            {"from": "Counterfactual Analyzer", "to": "Hypothesis Laboratory", "type": "recommendation"},
            {"from": "Pattern Discovery", "to": "Hypothesis Laboratory", "type": "recommendation"},
            {"from": "Market Memory", "to": "Trade Replay Engine", "type": "historical_analog"},
            {"from": "Hypothesis Laboratory", "to": "Rule Validation", "type": "manual_promotion_only"},
        ]
        validation_ids = {str(row.get("rule_id")) for row in validations}
        for hypothesis_id, hypothesis in hypotheses.items():
            node_id = f"hypothesis:{hypothesis_id}"
            nodes.append({"id": node_id, "type": "hypothesis", "status": hypothesis.get("status")})
            edges.append({"from": self.SUBSYSTEMS.get(hypothesis.get("source"), "Unknown"), "to": node_id, "type": "generated"})
            edges.append({"from": node_id, "to": "Hypothesis Laboratory", "type": "tracked"})
            if hypothesis_id in validation_ids: edges.append({"from": node_id, "to": "Rule Validation", "type": "manual_promotion"})
        return {"nodes": nodes, "edges": edges}

    def _health(self, hypotheses: Dict[str, Dict[str, Any]], validations: List[Dict[str, Any]]) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        stale = [row["hypothesis_id"] for row in hypotheses.values() if row.get("status") in {"Proposed", "Collecting Evidence"} and self._age_days(row.get("created_at"), now) >= self.STALE_HYPOTHESIS_DAYS]
        proposals: Dict[str, List[str]] = {}
        for row in hypotheses.values(): proposals.setdefault(self._normalize(row.get("proposal")), []).append(row["hypothesis_id"])
        duplicates = [ids for ids in proposals.values() if len(ids) > 1]
        contradictory = self._contradictions(hypotheses.values())
        failures = []
        for source in {row.get("source") for row in hypotheses.values()}:
            source_hypotheses = [row for row in hypotheses.values() if row.get("source") == source]
            completed = [row for row in source_hypotheses if row.get("status") in {"Validated", "Rejected"}]
            rejected = sum(1 for row in completed if row.get("status") == "Rejected")
            if len(completed) >= 3 and rejected / len(completed) >= .6: failures.append(self.SUBSYSTEMS.get(source, str(source)))
        return {"stale_hypotheses": stale, "duplicate_ideas": duplicates, "contradictory_recommendations": contradictory, "modules_consistently_failing_validation": failures, "health_status": "ATTENTION" if stale or duplicates or contradictory or failures else "HEALTHY"}

    def _trend(self) -> List[Dict[str, Any]]:
        return [{"date": str(row.get("created_at") or "")[:10], "hypotheses": len(row.get("recommendation_lifecycles") or []), "health": (row.get("health") or {}).get("health_status")} for row in self._records(self.snapshot_path)[-30:]]

    def _append_snapshot_if_changed(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prior = self._records(self.snapshot_path)
        latest = prior[-1] if prior else None
        comparable = {key: value for key, value in payload.items() if key not in {"created_at", "previous_snapshot_hash", "snapshot_hash", "trend"}}
        old = {key: value for key, value in (latest or {}).items() if key not in {"created_at", "previous_snapshot_hash", "snapshot_hash", "trend"}}
        if latest and comparable == old: return latest
        self.data_dir.mkdir(parents=True, exist_ok=True)
        immutable = {**payload, "previous_snapshot_hash": (latest or {}).get("snapshot_hash", "")}
        immutable["snapshot_hash"] = hashlib.sha256(json.dumps(immutable, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
        with self.snapshot_path.open("a", encoding="utf-8") as handle: handle.write(json.dumps(immutable, sort_keys=True, default=str) + "\n")
        return immutable

    def _append_lifecycle(self, lifecycle: Dict[str, Any], prior: Dict[str, Any] | None) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        record = {**lifecycle, "created_at": datetime.now(timezone.utc).isoformat(), "previous_lifecycle_hash": (prior or {}).get("lifecycle_hash", "")}
        record["lifecycle_hash"] = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
        with self.lifecycle_path.open("a", encoding="utf-8") as handle: handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    @staticmethod
    def _records(path: Path) -> List[Dict[str, Any]]:
        if not path.exists(): return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict): rows.append(row)
            except json.JSONDecodeError: continue
        return rows

    def _latest_by_key(self, path: Path, key: str) -> Dict[str, Dict[str, Any]]:
        return {str(row[key]): row for row in self._records(path) if row.get(key) is not None}

    @staticmethod
    def _normalize(value: Any) -> str:
        return " ".join(str(value or "").lower().split())

    @staticmethod
    def _age_days(value: Any, now: datetime) -> int:
        try: return max(0, (now - datetime.fromisoformat(str(value).replace("Z", "+00:00"))).days)
        except ValueError: return 0

    def _duration_days(self, row: Dict[str, Any]) -> float:
        return float(self._age_days(row.get("created_at"), datetime.now(timezone.utc)))

    @staticmethod
    def _contradictions(hypotheses: Iterable[Dict[str, Any]]) -> List[List[str]]:
        rows = list(hypotheses); pairs = []
        for index, left in enumerate(rows):
            left_text = str(left.get("proposal") or "").lower()
            for right in rows[index + 1:]:
                right_text = str(right.get("proposal") or "").lower()
                if (("skip" in left_text or "avoid" in left_text) and ("require" in right_text or "allow" in right_text)) or (("skip" in right_text or "avoid" in right_text) and ("require" in left_text or "allow" in left_text)):
                    pairs.append([left["hypothesis_id"], right["hypothesis_id"]])
        return pairs
