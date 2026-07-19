from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from engine.factors import FactorRegistry
from engine.factors.library import core_factors


@dataclass(frozen=True)
class FactorEvaluation:
    snapshot_id: str
    snapshot_date: str
    source_lineage: str
    signal: float | None
    rejection_reason: str | None


def core_factor_registry() -> FactorRegistry:
    registry = FactorRegistry()
    for factor in core_factors():
        registry.register(factor)
    return registry


def evaluate_registered_factor(*, factor_id: str, version: str, snapshots: Sequence[Mapping[str, Any]], registry: FactorRegistry | None = None) -> tuple[FactorEvaluation, ...]:
    selected = (registry or core_factor_registry()).load(factor_id, version)
    results = []
    for snapshot in sorted(snapshots, key=lambda row: (str(row.get("snapshot_date", "")), str(row.get("snapshot_id", "")))):
        snapshot_id, snapshot_date = str(snapshot.get("snapshot_id", "")), str(snapshot.get("snapshot_date", ""))
        lineage = str(snapshot.get("content_hash") or snapshot.get("source_lineage") or "")
        if not snapshot_id or not snapshot_date or not lineage:
            results.append(FactorEvaluation(snapshot_id, snapshot_date, lineage, None, "missing snapshot identity or source lineage"))
            continue
        try:
            results.append(FactorEvaluation(snapshot_id, snapshot_date, lineage, selected.evaluate(snapshot), None))
        except (TypeError, ValueError) as exc:
            results.append(FactorEvaluation(snapshot_id, snapshot_date, lineage, None, str(exc)))
    return tuple(results)