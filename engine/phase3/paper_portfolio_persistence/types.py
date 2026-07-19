from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from engine.phase3.paper_portfolio_engine.types import PaperPortfolioAudit, PaperTransaction, PerformanceSnapshot, PositionRecord
from engine.phase3.paper_portfolio_governance.types import (
    PaperPortfolioState,
    PaperRecommendationRecord,
    PaperRecommendationStatus,
)


class PaperEventType(str, Enum):
    RECOMMENDATION_RECORDED = "RECOMMENDATION_RECORDED"
    APPROVAL_RECORDED = "APPROVAL_RECORDED"
    RECOMMENDATION_REJECTED = "RECOMMENDATION_REJECTED"
    RECOMMENDATION_SUPERSEDED = "RECOMMENDATION_SUPERSEDED"
    RECOMMENDATION_EXPIRED = "RECOMMENDATION_EXPIRED"
    PAPER_FILL_RECORDED = "PAPER_FILL_RECORDED"
    POSITION_UPDATED = "POSITION_UPDATED"
    CASH_UPDATED = "CASH_UPDATED"
    PERFORMANCE_SNAPSHOT_RECORDED = "PERFORMANCE_SNAPSHOT_RECORDED"
    PORTFOLIO_RECONCILED = "PORTFOLIO_RECONCILED"
    CORPORATE_ACTION_PENDING = "CORPORATE_ACTION_PENDING"
    REPLAY_COMPLETED = "REPLAY_COMPLETED"


class HumanApprovalDecision(str, Enum):
    APPROVE_FOR_PAPER = "APPROVE_FOR_PAPER"
    REJECT_FOR_PAPER = "REJECT_FOR_PAPER"
    REVOKE_PAPER_APPROVAL = "REVOKE_PAPER_APPROVAL"


class HumanApprovalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class TaxLotStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    BLOCKED = "BLOCKED"


class CorporateActionType(str, Enum):
    STOCK_SPLIT = "STOCK_SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    CASH_DIVIDEND = "CASH_DIVIDEND"
    STOCK_DIVIDEND = "STOCK_DIVIDEND"
    MERGER = "MERGER"
    SPINOFF = "SPINOFF"
    TICKER_CHANGE = "TICKER_CHANGE"
    DELISTING = "DELISTING"


@dataclass(frozen=True)
class PaperPortfolioEvent:
    event_id: str
    event_type: PaperEventType
    sequence_number: int
    event_timestamp: str
    effective_timestamp: str
    aggregate_id: str
    recommendation_id: str | None
    transaction_id: str | None
    payload_version: str
    payload: Mapping[str, Any]
    previous_event_hash: str
    event_hash: str
    source_audit_references: Mapping[str, str] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    created_timestamp: str = "deterministic"


@dataclass(frozen=True)
class HumanApprovalRecord:
    approval_id: str
    recommendation_id: str
    approver_identity: str
    approval_decision: HumanApprovalDecision
    approval_timestamp: str
    approval_scope: str
    policy_version: str
    source_audit_reference: str
    reason: str
    expiration_timestamp: str
    superseded_by_reference: str | None
    status: HumanApprovalStatus


@dataclass(frozen=True)
class ReplayCheckpoint:
    sequence_number: int
    state_hash: str
    ledger_head_hash: str
    portfolio_state: PaperPortfolioState
    position_state: tuple[PositionRecord, ...]
    cash_state: float
    performance_state: PerformanceSnapshot
    schema_version: str
    created_timestamp: str
    source_audit_references: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperTaxLot:
    lot_id: str
    ticker: str
    opening_transaction_id: str
    opening_timestamp: str
    original_quantity: float
    remaining_quantity: float
    cost_per_share: float
    total_cost_basis: float
    realized_pnl: float
    status: TaxLotStatus
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CorporateActionRecord:
    action_id: str
    ticker: str
    action_type: CorporateActionType
    effective_timestamp: str
    payload: Mapping[str, Any]
    validated: bool
    source_audit_reference: str
    created_timestamp: str


@dataclass(frozen=True)
class ReplayState:
    recommendation_statuses: Mapping[str, PaperRecommendationStatus]
    approvals: tuple[HumanApprovalRecord, ...]
    transactions: tuple[PaperTransaction, ...]
    positions: tuple[PositionRecord, ...]
    cash_balance: float
    realized_pnl: float
    unrealized_pnl: float
    portfolio_nav: float
    performance_history: tuple[PerformanceSnapshot, ...]
    latest_state: PaperPortfolioState
    latest_audit_chain: tuple[PaperPortfolioAudit, ...]
    tax_lots: tuple[PaperTaxLot, ...]
    rejected_or_blocked_recommendations: tuple[str, ...]


@dataclass(frozen=True)
class ReplayValidationResult:
    deterministic: bool
    canonical_match: bool
    replay_head_hash: str
    canonical_state_hash: str
    replay_state_hash: str
    mismatch_reasons: tuple[str, ...]


@dataclass(frozen=True)
class PersistedBundle:
    portfolio_state: PaperPortfolioState
    positions: tuple[PositionRecord, ...]
    transactions: tuple[PaperTransaction, ...]
    performance_history: tuple[PerformanceSnapshot, ...]
    recommendations: tuple[PaperRecommendationRecord, ...]
    approvals: tuple[HumanApprovalRecord, ...]
    audits: tuple[PaperPortfolioAudit, ...]
    checkpoints: tuple[ReplayCheckpoint, ...]
    tax_lots: tuple[PaperTaxLot, ...]
