from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from engine.phase3.paper_portfolio_governance.types import PaperPortfolioState


@dataclass(frozen=True)
class PositionRecord:
    ticker: str
    quantity: float
    average_cost: float
    current_price: float
    market_value: float
    unrealized_gain_loss: float
    realized_gain_loss: float
    cost_basis: float
    weight: float
    first_purchase_date: str
    last_update: str
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperTransaction:
    transaction_id: str
    recommendation_id: str
    timestamp: str
    simulated_execution_price: float
    shares: float
    dollars: float
    commission: float
    slippage_assumption: float
    transaction_type: str
    audit_reference: str


@dataclass(frozen=True)
class PerformanceSnapshot:
    timestamp: str
    nav: float
    cash: float
    invested_capital: float
    daily_return: float
    cumulative_return: float
    benchmark_return: float
    active_return: float
    drawdown: float
    turnover: float
    concentration: float
    audit_reference: str


@dataclass(frozen=True)
class EngineAuditStep:
    step: str
    passed: bool
    detail: str
    timestamp: str
    record: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperPortfolioAudit:
    source_modules: tuple[str, ...]
    input_hashes: Mapping[str, str]
    validation_steps: tuple[EngineAuditStep, ...]
    executed_recommendations: tuple[str, ...]
    rejected_recommendations: tuple[str, ...]
    blocking_reasons: Mapping[str, tuple[str, ...]]
    reconciliation_ok: bool
    configuration_hash: str
    deterministic_execution_record: Mapping[str, Any]
    timestamp_metadata: Mapping[str, str]


@dataclass(frozen=True)
class PaperPortfolioEngineResult:
    updated_state: PaperPortfolioState
    simulated_fills: tuple[PaperTransaction, ...]
    positions: tuple[PositionRecord, ...]
    realized_pnl: float
    unrealized_pnl: float
    cash_balance: float
    holdings: Mapping[str, float]
    transaction_history: tuple[PaperTransaction, ...]
    portfolio_nav: float
    benchmark_comparison: Mapping[str, float]
    performance_snapshot: PerformanceSnapshot
    portfolio_audit: PaperPortfolioAudit
