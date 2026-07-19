from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class PaperRecommendationStatus(str, Enum):
    DRAFT = "DRAFT"
    BLOCKED = "BLOCKED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED_FOR_PAPER = "APPROVED_FOR_PAPER"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class PaperPortfolioState:
    as_of_timestamp: str
    paper_cash: float
    paper_holdings: Mapping[str, float]
    paper_weights: Mapping[str, float]
    total_paper_value: float
    provenance: Mapping[str, Any] = field(default_factory=dict)
    version: str = "1.0"


@dataclass(frozen=True)
class GovernanceValidationStep:
    step: str
    passed: bool
    detail: str
    timestamp: str
    record: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperRecommendationRecord:
    recommendation_id: str
    ticker: str
    recommendation_type: str
    current_paper_weight: float
    proposed_paper_weight: float
    expected_return: float
    confidence_adjusted_return: float
    confidence: float
    decision_eligibility: bool
    policy_status: str
    blocking_reasons: tuple[str, ...]
    source_audit_references: Mapping[str, str] = field(default_factory=dict)
    created_timestamp: str = "deterministic"
    expiration_timestamp: str = "deterministic"
    status: PaperRecommendationStatus = PaperRecommendationStatus.DRAFT


@dataclass(frozen=True)
class GovernanceAudit:
    source_modules: tuple[str, ...]
    policy_version: str
    input_hashes: Mapping[str, str]
    validation_steps: tuple[GovernanceValidationStep, ...]
    eligibility_checks: Mapping[str, bool]
    policy_checks: Mapping[str, bool]
    rejected_recommendations: tuple[str, ...]
    blocking_reasons: Mapping[str, tuple[str, ...]]
    approval_requirements: tuple[str, ...]
    configuration_hash: str
    deterministic_execution_record: Mapping[str, Any]
    timestamp_metadata: Mapping[str, str]


@dataclass(frozen=True)
class PaperGovernanceResult:
    recommendation_records: tuple[PaperRecommendationRecord, ...]
    proposed_paper_target_weights: Mapping[str, float]
    proposed_paper_cash_weight: float
    policy_checks: Mapping[str, bool]
    eligibility_checks: Mapping[str, bool]
    blocking_reasons: Mapping[str, tuple[str, ...]]
    recommendation_status: Mapping[str, PaperRecommendationStatus]
    governance_audit: GovernanceAudit
