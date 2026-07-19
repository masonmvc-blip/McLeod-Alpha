from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class SimulationScenario:
    method: str
    user_weights: Mapping[str, float] = field(default_factory=dict)
    assumptions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SimulationAuditStep:
    step: str
    passed: bool
    detail: str
    timestamp: str
    record: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SimulationAudit:
    assumptions: Mapping[str, Any]
    validation_steps: tuple[SimulationAuditStep, ...]
    timestamp: str
    deterministic_execution_record: Mapping[str, Any]
    configuration_hash: str


@dataclass(frozen=True)
class BacktestResult:
    start_date: str
    end_date: str
    benchmark: str
    cagr: float
    annual_volatility: float
    max_drawdown: float
    sharpe: float
    sortino: float
    hit_rate: float
    turnover: float
    audit: SimulationAudit
