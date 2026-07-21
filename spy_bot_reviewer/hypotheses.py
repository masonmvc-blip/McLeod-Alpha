"""Immutable advisory hypothesis registry for SPY replay research."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class HypothesisRegistry:
    """Tracks trading ideas before manual Rule Validation promotion."""

    VERSION = "hypothesis-lab.v1"
    STATUSES = {
        "Proposed", "Collecting Evidence", "Ready for Validation", "Validating",
        "Validated", "Rejected", "Superseded", "Archived",
    }

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.history_path = data_dir / "hypothesis_history.jsonl"

    def ingest(self, *, source: str, proposal: str, originating_evidence: Dict[str, Any], expected_improvement: float = 0.0, required_success_metrics: Optional[Dict[str, Any]] = None, minimum_sample_size: int = 20, confidence_target: float = 0.60, supporting_trade_ids: Optional[Iterable[str]] = None, reviewer_version: str = "unknown") -> Dict[str, Any]:
        hypothesis_id = "hyp-" + hashlib.sha256(f"{source}|{proposal}".encode("utf-8")).hexdigest()[:16]
        current = self.current().get(hypothesis_id)
        if current is None:
            current = self._append({
                "schema_version": self.VERSION,
                "hypothesis_id": hypothesis_id,
                "revision": 1,
                "source": source,
                "proposal": proposal,
                "originating_evidence": originating_evidence,
                "expected_improvement": float(expected_improvement or 0.0),
                "required_success_metrics": required_success_metrics or {"expectancy_improvement": "> 0", "positive_expectancy": True},
                "minimum_sample_size": int(minimum_sample_size),
                "confidence_target": float(confidence_target),
                "status": "Proposed",
                "supporting_trade_ids": sorted(set(map(str, supporting_trade_ids or []))),
                "conflicting_trade_ids": [],
                "reviewer_version": reviewer_version,
                "decision": None,
            })
        return current

    def refresh_evidence(self, bundles: Iterable[Dict[str, Any]], reviewer_version: str) -> List[Dict[str, Any]]:
        current = self.current()
        outcomes = self._trade_outcomes(bundles)
        refreshed = []
        for hypothesis in current.values():
            if hypothesis.get("status") in {"Validated", "Rejected", "Superseded", "Archived"}:
                continue
            support = sorted(trade_id for trade_id, pnl in outcomes.items() if pnl > 0)
            conflict = sorted(trade_id for trade_id, pnl in outcomes.items() if pnl < 0)
            sample_size = len(support) + len(conflict)
            confidence = len(support) / sample_size if sample_size else 0.0
            next_status = hypothesis.get("status")
            if hypothesis.get("status") != "Validating":
                if sample_size >= int(hypothesis.get("minimum_sample_size") or 20) and confidence >= float(hypothesis.get("confidence_target") or .60):
                    next_status = "Ready for Validation"
                else:
                    next_status = "Collecting Evidence"
            update = {**hypothesis, "revision": int(hypothesis.get("revision") or 0) + 1, "status": next_status, "supporting_trade_ids": support, "conflicting_trade_ids": conflict, "evidence_quality": round(confidence, 4), "sample_size": sample_size, "remaining_sample_size": max(0, int(hypothesis.get("minimum_sample_size") or 20) - sample_size), "reviewer_version": reviewer_version, "evidence_updated_at": datetime.now(timezone.utc).isoformat()}
            if self._material_change(hypothesis, update):
                refreshed.append(self._append(update))
            else:
                refreshed.append(hypothesis)
        return refreshed

    def manual_promote(self, hypothesis_id: str, reviewer_version: str) -> Dict[str, Any]:
        hypothesis = self.current().get(hypothesis_id)
        if hypothesis is None:
            raise KeyError("hypothesis not found")
        if hypothesis.get("status") != "Ready for Validation":
            raise ValueError("only Ready for Validation hypotheses may be promoted manually")
        return self._append({**hypothesis, "revision": int(hypothesis.get("revision") or 0) + 1, "status": "Validating", "decision": {"type": "manual_promotion_to_rule_validation", "automatic": False, "at": datetime.now(timezone.utc).isoformat()}, "reviewer_version": reviewer_version})

    def ranked(self) -> List[Dict[str, Any]]:
        rows = list(self.current().values())
        for row in rows:
            row["expected_impact_rank"] = round(float(row.get("expected_improvement") or 0.0) * max(1, int(row.get("sample_size") or 0)), 4)
        return sorted(rows, key=lambda row: (row.get("status") == "Ready for Validation", row.get("expected_impact_rank", 0), row.get("evidence_quality", 0)), reverse=True)

    def current(self) -> Dict[str, Dict[str, Any]]:
        latest = {}
        if not self.history_path.exists():
            return latest
        for line in self.history_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                if isinstance(record, dict) and record.get("hypothesis_id"):
                    latest[record["hypothesis_id"]] = record
            except json.JSONDecodeError:
                continue
        return latest

    def _append(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        history = self.current()
        previous = history.get(record["hypothesis_id"], {})
        immutable = {**record, "created_at": datetime.now(timezone.utc).isoformat(), "previous_revision_hash": previous.get("revision_hash", "")}
        canonical = json.dumps(immutable, sort_keys=True, separators=(",", ":"), default=str)
        immutable["revision_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(immutable, sort_keys=True, default=str) + "\n")
        return immutable

    @staticmethod
    def _trade_outcomes(bundles: Iterable[Dict[str, Any]]) -> Dict[str, float]:
        outcomes = {}
        for bundle in bundles:
            trade_id = str(bundle.get("trade_id") or (bundle.get("trade") or {}).get("trade_id") or "")
            actual = ((bundle.get("alternative_outcomes") or {}).get("actual") or {})
            if trade_id:
                outcomes[trade_id] = float(actual.get("pnl") or 0.0)
        return outcomes

    @staticmethod
    def _material_change(old: Dict[str, Any], new: Dict[str, Any]) -> bool:
        keys = ("status", "supporting_trade_ids", "conflicting_trade_ids", "sample_size", "evidence_quality")
        return any(old.get(key) != new.get(key) for key in keys)
