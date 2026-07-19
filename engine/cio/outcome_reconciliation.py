from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .decision_record import DecisionRecord


class OutcomeReconciliationError(ValueError):
    pass


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def confidence_bucket_from_confidence(confidence: float) -> str:
    score = _clamp(float(confidence))
    if score < 35.0:
        return "LOW"
    if score < 60.0:
        return "MEDIUM"
    if score < 80.0:
        return "HIGH"
    return "CONVICTION"


def _direction_for_action(action_type: str) -> str:
    action = str(action_type or "").strip().lower()
    if action in {"buy", "buy_to_open", "increase", "add", "long", "enter", "open"}:
        return "bullish"
    if action in {"trim", "sell", "reduce", "exit", "close"}:
        return "bearish"
    return "neutral"


@dataclass(frozen=True)
class RealizedOutcome:
    absolute_return: float
    benchmark_adjusted_return: float
    directionally_correct: bool
    confidence_bucket: str
    thesis_outcome: str
    evaluation_date: str
    notes: tuple[str, ...] = field(default_factory=tuple)
    decision_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["notes"] = list(self.notes)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RealizedOutcome:
        return cls(
            absolute_return=float(payload["absolute_return"]),
            benchmark_adjusted_return=float(payload["benchmark_adjusted_return"]),
            directionally_correct=bool(payload["directionally_correct"]),
            confidence_bucket=str(payload["confidence_bucket"]),
            thesis_outcome=str(payload["thesis_outcome"]),
            evaluation_date=str(payload["evaluation_date"]),
            notes=tuple(str(item) for item in payload.get("notes", []) or []),
            decision_id=str(payload.get("decision_id", "")),
        )


def reconcile_decision(
    *,
    record: DecisionRecord,
    evaluation_date: str,
    entry_price: float,
    current_price: float,
    benchmark_return: float,
    holding_period_days: int,
    thesis_status: str,
) -> RealizedOutcome:
    if float(entry_price) <= 0:
        raise OutcomeReconciliationError("entry_price must be positive.")
    if float(current_price) <= 0:
        raise OutcomeReconciliationError("current_price must be positive.")
    if int(holding_period_days) < 0:
        raise OutcomeReconciliationError("holding_period_days cannot be negative.")

    entry = float(entry_price)
    current = float(current_price)
    absolute_return = round((current / entry) - 1.0, 6)
    benchmark_adjusted_return = round(absolute_return - float(benchmark_return), 6)
    direction = _direction_for_action(record.action_type)

    if direction == "bullish" or direction == "neutral":
        directionally_correct = absolute_return >= 0.0 if direction == "bullish" else abs(absolute_return) <= abs(float(benchmark_return))
    else:
        directionally_correct = absolute_return <= 0.0

    thesis_outcome = str(thesis_status or "unknown").strip().lower() or "unknown"
    confidence_bucket = confidence_bucket_from_confidence(record.confidence)
    notes = (
        f"action_type={record.action_type}",
        f"holding_period_days={int(holding_period_days)}",
        f"benchmark_return={float(benchmark_return):.6f}",
        f"direction={direction}",
    )
    return RealizedOutcome(
        absolute_return=absolute_return,
        benchmark_adjusted_return=benchmark_adjusted_return,
        directionally_correct=directionally_correct,
        confidence_bucket=confidence_bucket,
        thesis_outcome=thesis_outcome,
        evaluation_date=str(evaluation_date),
        notes=notes,
        decision_id=record.decision_id,
    )