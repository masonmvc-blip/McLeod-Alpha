from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Tuple

from .errors import Phase3ApprovalError


class ApprovalState(str, Enum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED_FOR_EIPV = "APPROVED_FOR_EIPV"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ApprovalLogEntry:
    ticker: str
    from_state: ApprovalState
    to_state: ApprovalState
    actor: str
    reason: str
    timestamp: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


_ALLOWED_TRANSITIONS = {
    ApprovalState.RESEARCH_ONLY: {ApprovalState.READY_FOR_REVIEW, ApprovalState.REJECTED},
    ApprovalState.READY_FOR_REVIEW: {ApprovalState.APPROVED_FOR_EIPV, ApprovalState.REJECTED},
    ApprovalState.APPROVED_FOR_EIPV: set(),
    ApprovalState.REJECTED: {ApprovalState.RESEARCH_ONLY},
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _freeze_metadata(metadata: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return dict(metadata or {})


@dataclass(frozen=True)
class ApprovalWorkflow:
    ticker: str
    state: ApprovalState = ApprovalState.RESEARCH_ONLY
    audit_log: Tuple[ApprovalLogEntry, ...] = ()

    def transition(
        self,
        next_state: ApprovalState,
        *,
        actor: str,
        reason: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ApprovalWorkflow":
        if next_state not in _ALLOWED_TRANSITIONS[self.state]:
            raise Phase3ApprovalError(f"Invalid approval transition from {self.state} to {next_state}.")
        entry = ApprovalLogEntry(
            ticker=self.ticker,
            from_state=self.state,
            to_state=next_state,
            actor=str(actor or "system").strip() or "system",
            reason=str(reason or "").strip() or "explicit transition",
            timestamp=_utc_now_iso(),
            metadata=_freeze_metadata(metadata),
        )
        return replace(self, state=next_state, audit_log=self.audit_log + (entry,))

    def request_review(self, *, actor: str, reason: str, metadata: Mapping[str, Any] | None = None) -> "ApprovalWorkflow":
        return self.transition(ApprovalState.READY_FOR_REVIEW, actor=actor, reason=reason, metadata=metadata)

    def approve(self, *, actor: str, reason: str, metadata: Mapping[str, Any] | None = None) -> "ApprovalWorkflow":
        return self.transition(ApprovalState.APPROVED_FOR_EIPV, actor=actor, reason=reason, metadata=metadata)

    def reject(self, *, actor: str, reason: str, metadata: Mapping[str, Any] | None = None) -> "ApprovalWorkflow":
        return self.transition(ApprovalState.REJECTED, actor=actor, reason=reason, metadata=metadata)

    @property
    def is_approved_for_eipv(self) -> bool:
        return self.state is ApprovalState.APPROVED_FOR_EIPV
