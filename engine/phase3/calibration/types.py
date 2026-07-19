from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from engine.phase3.approval import ApprovalState


@dataclass(frozen=True)
class OutcomeRecord:
    ticker: str
    forecast_date: str
    evaluation_date: str
    expected_return: float
    realized_return: float | None
    expected_intrinsic_value: float
    realized_value: float | None
    confidence: float
    approval_state: ApprovalState
    evaluation_horizon: float
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CalibrationAuditStep:
    step: str
    passed: bool
    detail: str
    timestamp: str
    record: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CalibrationAudit:
    ticker: str
    measurable: bool
    missing_outcome_reasons: tuple[str, ...]
    steps: tuple[CalibrationAuditStep, ...]
    deterministic_record: Mapping[str, Any] = field(default_factory=dict)
