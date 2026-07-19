from __future__ import annotations

from hashlib import sha256
import json

from .types import (
    DatasetSpec,
    ExperimentSpec,
    RebalanceFrequency,
    SurvivorshipPolicy,
    TransactionAssumptions,
)


def deterministic_experiment_id(
    *,
    dataset_id: str,
    universe: str,
    date_range: tuple[str, str],
    rebalance_frequency: RebalanceFrequency,
    holding_period_days: int,
    benchmark: str,
    transaction_assumptions: TransactionAssumptions,
    survivorship_policy: SurvivorshipPolicy,
    look_ahead_prevention: bool,
    data_quality_score: float,
    factors: tuple[str, ...],
    hypothesis_id: str,
) -> str:
    payload = {
        "benchmark": benchmark,
        "data_quality_score": data_quality_score,
        "dataset_id": dataset_id,
        "date_range": [date_range[0], date_range[1]],
        "factors": list(sorted(factors)),
        "holding_period_days": holding_period_days,
        "hypothesis_id": hypothesis_id,
        "look_ahead_prevention": look_ahead_prevention,
        "rebalance_frequency": rebalance_frequency.value,
        "survivorship_policy": survivorship_policy.value,
        "transaction_assumptions": {
            "borrow_cost_bps": transaction_assumptions.borrow_cost_bps,
            "commission_bps": transaction_assumptions.commission_bps,
            "slippage_bps": transaction_assumptions.slippage_bps,
        },
        "universe": universe,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def create_experiment_spec(
    *,
    dataset: DatasetSpec,
    universe: str,
    date_range: tuple[str, str],
    rebalance_frequency: RebalanceFrequency,
    holding_period_days: int,
    benchmark: str,
    transaction_assumptions: TransactionAssumptions,
    survivorship_policy: SurvivorshipPolicy,
    look_ahead_prevention: bool,
    data_quality_score: float,
    factors: tuple[str, ...],
    hypothesis_id: str,
    provenance: dict[str, str],
) -> ExperimentSpec:
    if holding_period_days <= 0:
        raise ValueError("holding_period_days must be > 0")
    experiment_id = deterministic_experiment_id(
        dataset_id=dataset.dataset_id,
        universe=universe,
        date_range=date_range,
        rebalance_frequency=rebalance_frequency,
        holding_period_days=holding_period_days,
        benchmark=benchmark,
        transaction_assumptions=transaction_assumptions,
        survivorship_policy=survivorship_policy,
        look_ahead_prevention=look_ahead_prevention,
        data_quality_score=data_quality_score,
        factors=factors,
        hypothesis_id=hypothesis_id,
    )
    return ExperimentSpec(
        experiment_id=experiment_id,
        dataset=dataset,
        universe=universe,
        date_range=date_range,
        rebalance_frequency=rebalance_frequency,
        holding_period_days=holding_period_days,
        benchmark=benchmark,
        transaction_assumptions=transaction_assumptions,
        survivorship_policy=survivorship_policy,
        look_ahead_prevention=look_ahead_prevention,
        data_quality_score=data_quality_score,
        factors=tuple(sorted(factors)),
        hypothesis_id=hypothesis_id,
        provenance=dict(sorted(provenance.items())),
    )
