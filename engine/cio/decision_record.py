from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from typing import Any, TYPE_CHECKING


if TYPE_CHECKING:
    from .outcome_reconciliation import RealizedOutcome


class DecisionJournalError(ValueError):
    pass


class DecisionJournalConflictError(DecisionJournalError):
    pass


class DecisionJournalMissingRecordError(DecisionJournalError):
    pass


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    created_at: str
    as_of_date: str
    symbol: str
    action_type: str
    priority: int
    recommendation: str
    confidence: float
    expected_benefit: str
    expected_risk: str
    supporting_evidence: tuple[str, ...] = field(default_factory=tuple)
    conflicting_evidence: tuple[str, ...] = field(default_factory=tuple)
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    invalidation_conditions: tuple[str, ...] = field(default_factory=tuple)
    source_brief_id: str = ""
    status: str = "OPEN"
    realized_outcome: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["supporting_evidence"] = list(self.supporting_evidence)
        payload["conflicting_evidence"] = list(self.conflicting_evidence)
        payload["assumptions"] = list(self.assumptions)
        payload["invalidation_conditions"] = list(self.invalidation_conditions)
        if self.realized_outcome is not None and hasattr(self.realized_outcome, "to_dict"):
            payload["realized_outcome"] = self.realized_outcome.to_dict()
        return payload

    def to_json_line(self) -> str:
        return _stable_json(self.to_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DecisionRecord:
        realized_outcome = payload.get("realized_outcome")
        if isinstance(realized_outcome, dict):
            from .outcome_reconciliation import RealizedOutcome

            realized_outcome = RealizedOutcome.from_dict(realized_outcome)

        return cls(
            decision_id=str(payload["decision_id"]),
            created_at=str(payload["created_at"]),
            as_of_date=str(payload["as_of_date"]),
            symbol=str(payload["symbol"]),
            action_type=str(payload["action_type"]),
            priority=int(payload["priority"]),
            recommendation=str(payload["recommendation"]),
            confidence=float(payload["confidence"]),
            expected_benefit=str(payload["expected_benefit"]),
            expected_risk=str(payload["expected_risk"]),
            supporting_evidence=tuple(str(item) for item in payload.get("supporting_evidence", []) or []),
            conflicting_evidence=tuple(str(item) for item in payload.get("conflicting_evidence", []) or []),
            assumptions=tuple(str(item) for item in payload.get("assumptions", []) or []),
            invalidation_conditions=tuple(str(item) for item in payload.get("invalidation_conditions", []) or []),
            source_brief_id=str(payload.get("source_brief_id", "")),
            status=str(payload.get("status", "OPEN")),
            realized_outcome=realized_outcome,
        )


def build_decision_id(
    *,
    as_of_date: str,
    symbol: str,
    action_type: str,
    recommendation: str,
    source_brief_id: str,
) -> str:
    payload = "|".join(
        (
            _normalize_text(as_of_date),
            _normalize_text(symbol).upper(),
            _normalize_text(action_type).lower(),
            _normalize_text(recommendation),
            _normalize_text(source_brief_id),
        )
    )
    return "DEC-" + sha256(payload.encode("utf-8")).hexdigest()[:20].upper()