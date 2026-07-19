from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class OperationsMode(str, Enum):
    DISABLED = "DISABLED"
    VALIDATION_ONLY = "VALIDATION_ONLY"
    PAPER_OBSERVATION = "PAPER_OBSERVATION"
    PAPER_MANUAL = "PAPER_MANUAL"
    HALTED = "HALTED"


class SessionStatus(str, Enum):
    CREATED = "CREATED"
    PREFLIGHT_BLOCKED = "PREFLIGHT_BLOCKED"
    READY = "READY"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    HALTED = "HALTED"
    FAILED = "FAILED"


class OperationType(str, Enum):
    RECORD_RECOMMENDATION = "RECORD_RECOMMENDATION"
    RECORD_APPROVAL = "RECORD_APPROVAL"
    RECORD_REJECTION = "RECORD_REJECTION"
    RECORD_SUPERSESSION = "RECORD_SUPERSESSION"
    RECORD_EXPIRATION = "RECORD_EXPIRATION"
    RECORD_PAPER_FILL = "RECORD_PAPER_FILL"
    RECORD_PERFORMANCE_SNAPSHOT = "RECORD_PERFORMANCE_SNAPSHOT"
    RECONCILE_PORTFOLIO = "RECONCILE_PORTFOLIO"
    CREATE_CHECKPOINT = "CREATE_CHECKPOINT"
    CREATE_BACKUP = "CREATE_BACKUP"
    VERIFY_BACKUP = "VERIFY_BACKUP"
    TEST_RESTORE = "TEST_RESTORE"
    HALT_OPERATIONS = "HALT_OPERATIONS"


class RequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    BLOCKED = "BLOCKED"
    APPROVED_MANUALLY = "APPROVED_MANUALLY"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    HALTED = "HALTED"


@dataclass(frozen=True)
class PaperOperationsPolicy:
    operations_mode: OperationsMode
    required_milestone_markers: tuple[str, ...]
    required_validation_suites: tuple[str, ...]
    maximum_ledger_age_minutes: int
    maximum_price_data_age_minutes: int
    maximum_recommendation_age_minutes: int
    maximum_checkpoint_age_minutes: int
    minimum_backup_count: int
    backup_retention_policy: str
    reconciliation_tolerance: float
    allowed_operating_windows: tuple[str, ...]
    required_operator_approvals: tuple[str, ...]
    required_preflight_checks: tuple[str, ...]
    required_post_run_checks: tuple[str, ...]
    corporate_action_blocking_policy: str
    degraded_mode_policy: str
    automatic_halt_conditions: tuple[str, ...]
    version: str

    def validate(self) -> None:
        if self.operations_mode not in set(OperationsMode):
            raise ValueError("Unsupported operations mode.")
        if self.operations_mode not in {OperationsMode.DISABLED, OperationsMode.VALIDATION_ONLY, OperationsMode.PAPER_OBSERVATION, OperationsMode.PAPER_MANUAL, OperationsMode.HALTED}:
            raise ValueError("Autonomous operations mode is forbidden.")
        if not self.required_milestone_markers:
            raise ValueError("required_milestone_markers cannot be empty.")
        if self.maximum_ledger_age_minutes <= 0:
            raise ValueError("maximum_ledger_age_minutes must be positive.")
        if self.maximum_price_data_age_minutes <= 0:
            raise ValueError("maximum_price_data_age_minutes must be positive.")
        if self.maximum_recommendation_age_minutes <= 0:
            raise ValueError("maximum_recommendation_age_minutes must be positive.")
        if self.maximum_checkpoint_age_minutes <= 0:
            raise ValueError("maximum_checkpoint_age_minutes must be positive.")
        if self.minimum_backup_count < 0:
            raise ValueError("minimum_backup_count must be >= 0.")
        if self.reconciliation_tolerance < 0.0:
            raise ValueError("reconciliation_tolerance must be >= 0.")
        if not self.allowed_operating_windows:
            raise ValueError("allowed_operating_windows cannot be empty.")
        if not self.required_preflight_checks:
            raise ValueError("required_preflight_checks cannot be empty.")
        if not self.required_post_run_checks:
            raise ValueError("required_post_run_checks cannot be empty.")
        if not self.version.strip():
            raise ValueError("Policy version is required.")

    @classmethod
    def default(cls) -> "PaperOperationsPolicy":
        return cls(
            operations_mode=OperationsMode.VALIDATION_ONLY,
            required_milestone_markers=(
                "data/research/logs/SystemAudit_Complete.json",
                "data/research/logs/RepositoryHygiene_Validated.json",
                "data/research/logs/PaperPortfolioGovernance_Validated.json",
                "data/research/logs/PaperPortfolioEngine_Validated.json",
                "data/research/logs/PaperPortfolioPersistenceReplay_Validated.json",
            ),
            required_validation_suites=(
                "test_phase3_invariants",
                "test_paper_portfolio_governance_invariants",
                "test_paper_portfolio_engine_invariants",
                "test_paper_portfolio_persistence_replay_invariants",
            ),
            maximum_ledger_age_minutes=60,
            maximum_price_data_age_minutes=60,
            maximum_recommendation_age_minutes=72 * 60,
            maximum_checkpoint_age_minutes=60,
            minimum_backup_count=1,
            backup_retention_policy="retain_last_10_backups",
            reconciliation_tolerance=1e-8,
            allowed_operating_windows=("00:00-23:59",),
            required_operator_approvals=("risk",),
            required_preflight_checks=(
                "milestones",
                "frozen_hashes",
                "hygiene",
                "ledger_integrity",
                "replay_vs_canonical",
                "checkpoint_match",
                "reconciliation",
                "corporate_actions",
                "approvals",
                "price_freshness",
                "backups",
                "restore_test",
                "schema_version",
                "operating_window",
                "access_path_scan",
            ),
            required_post_run_checks=("reconcile", "checkpoint", "backup", "verify_backup"),
            corporate_action_blocking_policy="block_unvalidated_actions_on_active_positions",
            degraded_mode_policy="degraded_mode_forbids_manual_fill_recording",
            automatic_halt_conditions=(
                "ledger_integrity_failed",
                "replay_diverged",
                "reconciliation_mismatch",
                "checkpoint_mismatch",
                "schema_changed",
                "backup_failed",
                "restore_failed",
                "stale_price_data",
                "corporate_action_unresolved",
                "invalid_lifecycle_transition",
                "broker_access_attempted",
                "production_access_attempted",
                "autonomous_approval_attempted",
                "frozen_hash_drift",
            ),
            version="paper-operations-policy-v1",
        )


@dataclass(frozen=True)
class PaperOperationsState:
    mode: OperationsMode
    session_id: str
    session_status: SessionStatus
    session_start_timestamp: str
    session_end_timestamp: str | None
    latest_ledger_sequence: int
    latest_ledger_hash: str
    latest_checkpoint_sequence: int
    latest_portfolio_state_hash: str
    latest_reconciliation_status: str
    latest_backup_status: str
    latest_restore_test_status: str
    latest_price_data_timestamp: str
    active_blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    operator_identity: str
    policy_version: str
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperOperationsSession:
    session_id: str
    requested_mode: OperationsMode
    approved_mode: OperationsMode
    operator_identity: str
    operator_approval_reference: str
    preflight_result: Mapping[str, Any]
    opened_timestamp: str
    closed_timestamp: str | None
    session_status: SessionStatus
    actions_attempted: int
    actions_completed: int
    actions_rejected: int
    halt_reason: str | None
    audit_reference: str


@dataclass(frozen=True)
class PaperOperationRequest:
    request_id: str
    session_id: str
    operation_type: OperationType
    recommendation_id: str | None
    operator_identity: str
    operator_approval_reference: str
    requested_timestamp: str
    effective_timestamp: str
    source_audit_references: Mapping[str, str]
    request_status: RequestStatus
    blocking_reasons: tuple[str, ...]
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperReconciliationResult:
    passed: bool
    ledger_head_hash: str
    canonical_state_hash: str
    replay_state_hash: str
    checkpoint_state_hash: str
    cash_match: bool
    positions_match: bool
    tax_lots_match: bool
    realized_pnl_match: bool
    unrealized_pnl_match: bool
    nav_match: bool
    recommendation_statuses_match: bool
    approvals_match: bool
    transactions_match: bool
    performance_history_match: bool
    mismatch_reasons: tuple[str, ...]


@dataclass(frozen=True)
class PaperHealthCheckResult:
    status: HealthStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    halt_required: bool
    audit_reference: str


@dataclass(frozen=True)
class PaperOperationsAudit:
    source_modules: tuple[str, ...]
    input_hashes: Mapping[str, str]
    preflight_checks: Mapping[str, bool]
    reconciliation_result: PaperReconciliationResult
    health_result: PaperHealthCheckResult
    operation_requests: tuple[str, ...]
    automatic_halt_conditions_triggered: tuple[str, ...]
    timestamp_metadata: Mapping[str, str]
    configuration_hash: str


@dataclass(frozen=True)
class PaperOperationsPreflightResult:
    passed: bool
    checks: Mapping[str, bool]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    latest_ledger_hash: str
    latest_state_hash: str
    latest_checkpoint_sequence: int
    audit_reference: str
