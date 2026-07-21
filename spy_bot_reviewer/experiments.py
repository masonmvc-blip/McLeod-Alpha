"""Immutable, replay-only experiment framework for hypothesis evaluation."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


class ExperimentFramework:
    """Formal experiment gate between Hypothesis Lab and manual Rule Validation."""

    VERSION = "experiment-framework.v1"
    MODES = {"A/B", "SHADOW", "REPLAY_ONLY"}
    DEFAULT_ALPHA = 0.05
    DEFAULT_POWER = 0.80

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.history_path = data_dir / "experiment_history.jsonl"

    def sync(self, hypotheses: Dict[str, Dict[str, Any]], bundles: Iterable[Dict[str, Any]], provenance: Dict[str, Any]) -> List[Dict[str, Any]]:
        bundle_list = list(bundles)
        current = self.current()
        for hypothesis_id, hypothesis in hypotheses.items():
            if hypothesis.get("status") in {"Rejected", "Superseded", "Archived"}: continue
            experiment = current.get(hypothesis_id)
            if experiment is None:
                experiment = self._append(self._protocol(hypothesis, provenance))
            if experiment.get("status") in {"Concluded Success", "Concluded Failure", "Archived"}: continue
            analysis = self._analyze(experiment, bundle_list)
            updated = {**experiment, "revision": int(experiment.get("revision") or 0) + 1, "status": analysis["status"], "interim": analysis, "enrolled_trade_ids": analysis["enrolled_trade_ids"], "updated_at": datetime.now(timezone.utc).isoformat()}
            if self._material_change(experiment, updated): self._append(updated)
        return self.ranked()

    def current(self) -> Dict[str, Dict[str, Any]]:
        latest = {}
        if not self.history_path.exists(): return latest
        for line in self.history_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                if isinstance(record, dict) and record.get("hypothesis_id"): latest[record["hypothesis_id"]] = record
            except json.JSONDecodeError: continue
        return latest

    def eligible_for_manual_promotion(self, hypothesis_id: str) -> bool:
        experiment = self.current().get(hypothesis_id) or {}
        return experiment.get("status") == "Concluded Success"

    def ranked(self) -> List[Dict[str, Any]]:
        rows = list(self.current().values())
        overlap = self._overlaps(rows)
        for row in rows:
            row["overlaps"] = overlap.get(row.get("experiment_id"), [])
            row["contaminated"] = bool(row["overlaps"])
        return sorted(rows, key=lambda row: (row.get("status") == "Concluded Success", float((row.get("interim") or {}).get("probability_of_success") or 0), len(row.get("enrolled_trade_ids") or [])), reverse=True)

    def _protocol(self, hypothesis: Dict[str, Any], provenance: Dict[str, Any]) -> Dict[str, Any]:
        expected = abs(float(hypothesis.get("expected_improvement") or 0.10)) or 0.10
        target = max(int(hypothesis.get("minimum_sample_size") or 20), self._sample_size(expected))
        mode = str(hypothesis.get("experiment_mode") or "REPLAY_ONLY").upper()
        if mode not in self.MODES:
            mode = "REPLAY_ONLY"
        return {
            "schema_version": self.VERSION,
            "experiment_id": "exp-" + hashlib.sha256(hypothesis["hypothesis_id"].encode("utf-8")).hexdigest()[:16],
            "hypothesis_id": hypothesis["hypothesis_id"],
            "revision": 1,
            "mode": mode,
            "status": "Protocol",
            "protocol": {"success_criteria": {"expectancy_improvement": "> 0", "confidence_interval_excludes_zero": True}, "expected_effect_size": expected, "statistical_power_target": self.DEFAULT_POWER, "alpha": self.DEFAULT_ALPHA, "sample_size_calculation": target, "stopping_rules": ["success only when sequential adjusted p-value < alpha and effect > 0", "futility when target sample reached and effect <= 0", "manual promotion only after Concluded Success"], "sequential_testing": "Bonferroni alpha spending across each interim look"},
            "provenance": {"strategy_version": provenance.get("strategy_version", "unknown"), "feature_set": provenance.get("feature_set", "replay-candles-v1"), "reviewer_version": provenance.get("reviewer_version"), "prompt_version": provenance.get("prompt_version"), "market_memory_version": provenance.get("market_memory_version"), "data_schema_version": provenance.get("data_schema_version", "replay-bundle.v2")},
            "supporting_trade_ids": list(hypothesis.get("supporting_trade_ids") or []), "enrolled_trade_ids": [], "interim": {}, "manual_approval_required": True, "live_engine_isolated": True, "enrollment_policy": "automated replay enrollment only" if mode == "REPLAY_ONLY" else "manual, non-live enrollment required",
        }

    def _analyze(self, experiment: Dict[str, Any], bundles: List[Dict[str, Any]]) -> Dict[str, Any]:
        supporting = set((experiment.get("supporting_trade_ids") or []))
        hypothesis_id = experiment["hypothesis_id"]
        records = []
        for bundle in bundles:
            trade_id = str(bundle.get("trade_id") or (bundle.get("trade") or {}).get("trade_id") or "")
            pnl = float(((bundle.get("alternative_outcomes") or {}).get("actual") or {}).get("pnl") or 0)
            if trade_id: records.append((trade_id, pnl, trade_id in supporting))
        if not supporting: records = [(trade_id, pnl, True) for trade_id, pnl, _ in records]
        treatment = [pnl for _, pnl, eligible in records if eligible]
        control = [pnl for _, pnl, eligible in records if not eligible]
        if not control: control = [0.0] * max(1, len(treatment))
        effect = self._mean(treatment) - self._mean(control)
        se = math.sqrt(self._variance(treatment) / max(1, len(treatment)) + self._variance(control) / max(1, len(control)))
        ci_low, ci_high = effect - 1.96 * se, effect + 1.96 * se
        z = effect / se if se else (99.0 if effect > 0 else -99.0 if effect < 0 else 0.0)
        raw_p = math.erfc(abs(z) / math.sqrt(2))
        looks = max(1, int(experiment.get("revision") or 1))
        adjusted_p = min(1.0, raw_p * looks)
        target = int((experiment.get("protocol") or {}).get("sample_size_calculation") or 20)
        enrolled = [trade_id for trade_id, _, _ in records]
        probability = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        if len(treatment) >= target and effect <= 0: status = "Concluded Failure"
        elif effect > 0 and ci_low > 0 and adjusted_p < self.DEFAULT_ALPHA: status = "Concluded Success"
        else: status = "Active"
        return {"hypothesis_id": hypothesis_id, "enrolled_trade_ids": enrolled, "treatment_count": len(treatment), "control_count": len(control), "effect_size": round(effect, 4), "confidence_interval": [round(ci_low, 4), round(ci_high, 4)], "raw_p_value": round(raw_p, 6), "sequential_adjusted_p_value": round(adjusted_p, 6), "interim_looks": looks, "probability_of_success": round(probability, 4), "estimated_remaining_sample_size": max(0, target - len(treatment)), "expected_alpha_improvement": round(effect, 4), "status": status}

    def _overlaps(self, experiments: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        output = {row.get("experiment_id"): [] for row in experiments}
        for index, left in enumerate(experiments):
            left_ids = set(left.get("enrolled_trade_ids") or [])
            for right in experiments[index + 1:]:
                shared = sorted(left_ids & set(right.get("enrolled_trade_ids") or []))
                if shared:
                    item = {"experiment_id": right.get("experiment_id"), "shared_trade_ids": shared, "type": "enrollment_contamination"}
                    output[left.get("experiment_id")].append(item)
                    output[right.get("experiment_id")].append({"experiment_id": left.get("experiment_id"), "shared_trade_ids": shared, "type": "enrollment_contamination"})
        return output

    def _append(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        prior = self.current().get(record["hypothesis_id"], {})
        immutable = {**record, "created_at": datetime.now(timezone.utc).isoformat(), "previous_revision_hash": prior.get("revision_hash", "")}
        immutable["revision_hash"] = hashlib.sha256(json.dumps(immutable, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
        with self.history_path.open("a", encoding="utf-8") as handle: handle.write(json.dumps(immutable, sort_keys=True, default=str) + "\n")
        return immutable

    @staticmethod
    def _material_change(old: Dict[str, Any], new: Dict[str, Any]) -> bool:
        keys = ("status", "enrolled_trade_ids", "interim")
        return any(old.get(key) != new.get(key) for key in keys)

    @staticmethod
    def _mean(values: List[float]) -> float: return sum(values) / len(values) if values else 0.0
    @staticmethod
    def _variance(values: List[float]) -> float:
        if len(values) < 2: return 1.0
        mean = ExperimentFramework._mean(values); return sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    @staticmethod
    def _sample_size(effect: float) -> int: return max(20, math.ceil(16 / max(effect * effect, .01)))
