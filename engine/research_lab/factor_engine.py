from __future__ import annotations

from typing import Any, Mapping, Sequence

from .factor_definition import FactorDefinition


def evaluate_factors(snapshots: Sequence[Mapping[str, Any]], factors: Sequence[FactorDefinition]) -> tuple[dict[str, Any], ...]:
    return tuple({"snapshot_id": str(snapshot["snapshot_id"]), "snapshot_date": str(snapshot["snapshot_date"]), "signals": {factor.name: factor.evaluate(snapshot) for factor in factors}} for snapshot in snapshots)