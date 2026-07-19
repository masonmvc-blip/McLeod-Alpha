from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class OperatorRole(str, Enum):
    PAPER_OPERATOR = "PAPER_OPERATOR"
    PAPER_APPROVER = "PAPER_APPROVER"
    RISK_REVIEWER = "RISK_REVIEWER"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    INCIDENT_OWNER = "INCIDENT_OWNER"
    READ_ONLY_OBSERVER = "READ_ONLY_OBSERVER"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AttestationType(str, Enum):
    RUNBOOK_REVIEWED = "RUNBOOK_REVIEWED"
    BACKUP_POLICY_APPROVED = "BACKUP_POLICY_APPROVED"
    RESTORE_TEST_APPROVED = "RESTORE_TEST_APPROVED"
    RECONCILIATION_POLICY_APPROVED = "RECONCILIATION_POLICY_APPROVED"
    CORPORATE_ACTION_PROCEDURE_APPROVED = "CORPORATE_ACTION_PROCEDURE_APPROVED"
    INCIDENT_RESPONSE_APPROVED = "INCIDENT_RESPONSE_APPROVED"
    PAPER_ONLY_BOUNDARY_APPROVED = "PAPER_ONLY_BOUNDARY_APPROVED"
    NO_BROKER_ACCESS_CONFIRMED = "NO_BROKER_ACCESS_CONFIRMED"
    NO_PRODUCTION_PORTFOLIO_ACCESS_CONFIRMED = "NO_PRODUCTION_PORTFOLIO_ACCESS_CONFIRMED"
    MANUAL_APPROVAL_ONLY_CONFIRMED = "MANUAL_APPROVAL_ONLY_CONFIRMED"
    ACTIVATION_WINDOW_APPROVED = "ACTIVATION_WINDOW_APPROVED"


class AttestationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ActivationStatus(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    BLOCKED = "BLOCKED"
    READY_FOR_MANUAL_PAPER = "READY_FOR_MANUAL_PAPER"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class PaperActivationPolicy:
    required_milestone_markers: tuple[str, ...]
    required_operator_roles: tuple[OperatorRole, ...]
    minimum_independent_approvers: int
    prohibited_role_overlap_rules: Mapping[str, tuple[OperatorRole, ...]]
    required_runbook_version: str
    required_backup_cadence: str
    required_restore_test_cadence: str
    required_reconciliation_cadence: str
    required_reporting_cadence: str
    required_escalation_contacts: tuple[str, ...]
    required_corporate_action_procedure: str
    required_incident_response_procedure: str
    required_rollback_procedure: str
    required_manual_approval_scope: str
    activation_expiration_period_hours: int
    maximum_unresolved_warnings: int
    version: str

    def validate(self) -> None:
        if not self.required_milestone_markers:
            raise ValueError("required_milestone_markers cannot be empty")
        if not self.required_operator_roles:
            raise ValueError("required_operator_roles cannot be empty")
        if self.minimum_independent_approvers < 1:
            raise ValueError("minimum_independent_approvers must be >= 1")
        if not self.required_runbook_version.strip():
            raise ValueError("required_runbook_version is required")
        if not self.required_backup_cadence.strip():
            raise ValueError("required_backup_cadence is required")
        if not self.required_restore_test_cadence.strip():
            raise ValueError("required_restore_test_cadence is required")
        if not self.required_reconciliation_cadence.strip():
            raise ValueError("required_reconciliation_cadence is required")
        if not self.required_reporting_cadence.strip():
            raise ValueError("required_reporting_cadence is required")
        if not self.required_escalation_contacts:
            raise ValueError("required_escalation_contacts cannot be empty")
        if self.activation_expiration_period_hours <= 0:
            raise ValueError("activation_expiration_period_hours must be positive")
        if self.maximum_unresolved_warnings < 0:
            raise ValueError("maximum_unresolved_warnings must be >= 0")
        if not self.version.strip():
            raise ValueError("version is required")

    @classmethod
    def default(cls) -> "PaperActivationPolicy":
        return cls(
            required_milestone_markers=(
                "data/research/logs/IndependentSystemCertification_Validated.json",
                "data/research/logs/PaperPortfolioOperationsReadiness_Validated.json",
            ),
            required_operator_roles=(
                OperatorRole.PAPER_OPERATOR,
                OperatorRole.PAPER_APPROVER,
                OperatorRole.RISK_REVIEWER,
                OperatorRole.SYSTEM_ADMIN,
                OperatorRole.INCIDENT_OWNER,
            ),
            minimum_independent_approvers=2,
            prohibited_role_overlap_rules={
                "operator_vs_approver": (OperatorRole.PAPER_OPERATOR, OperatorRole.PAPER_APPROVER),
                "operator_vs_risk": (OperatorRole.PAPER_OPERATOR, OperatorRole.RISK_REVIEWER),
                "approver_vs_admin": (OperatorRole.PAPER_APPROVER, OperatorRole.SYSTEM_ADMIN),
            },
            required_runbook_version="paper-ops-runbook-v1",
            required_backup_cadence="daily",
            required_restore_test_cadence="weekly",
            required_reconciliation_cadence="daily",
            required_reporting_cadence="daily",
            required_escalation_contacts=("incident_owner", "risk_reviewer"),
            required_corporate_action_procedure="reports/paper_portfolio_corporate_action_procedure_v1.md",
            required_incident_response_procedure="reports/paper_portfolio_incident_response_v1.md",
            required_rollback_procedure="reports/paper_portfolio_rollback_procedure_v1.md",
            required_manual_approval_scope="manual_paper_only",
            activation_expiration_period_hours=24,
            maximum_unresolved_warnings=0,
            version="paper-activation-policy-v1",
        )


@dataclass(frozen=True)
class OperatorRoleAssignment:
    assignment_id: str
    operator_identity: str
    role: OperatorRole
    effective_timestamp: str
    expiration_timestamp: str
    approval_reference: str
    status: AssignmentStatus
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActivationAttestation:
    attestation_id: str
    attestation_type: AttestationType
    operator_identity: str
    operator_role: OperatorRole
    signed_timestamp: str
    expiration_timestamp: str
    evidence_references: tuple[str, ...]
    policy_version: str
    status: AttestationStatus
    revocation_reference: str | None
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperActivationDecision:
    decision_id: str
    decision_timestamp: str
    requested_mode: str
    approved_mode: str
    activation_status: ActivationStatus
    expiration_timestamp: str
    satisfied_prerequisites: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    approver_identities: tuple[str, ...]
    role_assignments: tuple[str, ...]
    attestation_references: tuple[str, ...]
    milestone_references: tuple[str, ...]
    audit_reference: str
    provenance: Mapping[str, Any] = field(default_factory=dict)
