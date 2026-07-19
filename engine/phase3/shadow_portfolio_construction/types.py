from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class PortfolioConstraints:
    maximum_position_weight: float
    minimum_position_weight: float
    maximum_sector_weight: float
    maximum_total_invested_capital: float
    minimum_cash_reserve: float
    maximum_number_of_holdings: int
    maximum_turnover: float
    prohibited_tickers: tuple[str, ...] = ()
    required_tickers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplacementEvaluation:
    incumbent_ticker: str
    candidate_ticker: str
    expected_return_improvement: float
    confidence_adjusted_improvement: float
    estimated_turnover: float
    constraint_impact: Mapping[str, Any] = field(default_factory=dict)
    eligibility_status: bool = False
    blocking_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShadowAllocationAuditStep:
    step: str
    passed: bool
    detail: str
    timestamp: str
    record: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ShadowAllocationAudit:
    inputs: Mapping[str, Any]
    validation_steps: tuple[ShadowAllocationAuditStep, ...]
    allocation_method: str
    constraint_checks: tuple[str, ...]
    rejected_candidates: tuple[str, ...]
    configuration_hash: str
    deterministic_execution_record: Mapping[str, Any]
    timestamp_metadata: Mapping[str, str]
