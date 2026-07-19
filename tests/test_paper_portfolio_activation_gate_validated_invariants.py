from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta
from pathlib import Path
import json

import pytest

from engine.phase3.paper_portfolio_activation_gate.model import PaperActivationGateModel
from engine.phase3.paper_portfolio_activation_gate.types import (
    ActivationAttestation,
    ActivationStatus,
    AssignmentStatus,
    AttestationStatus,
    AttestationType,
    OperatorRole,
    OperatorRoleAssignment,
    PaperActivationPolicy,
)


def _now() -> datetime:
    return datetime(2026, 7, 18, 14, 0, 0)


def _role(
    assignment_id: str,
    identity: str,
    role: OperatorRole,
    *,
    expires_hours: int = 24,
    status: AssignmentStatus = AssignmentStatus.ACTIVE,
) -> OperatorRoleAssignment:
    now = _now()
    return OperatorRoleAssignment(
        assignment_id=assignment_id,
        operator_identity=identity,
        role=role,
        effective_timestamp=now.isoformat(),
        expiration_timestamp=(now + timedelta(hours=expires_hours)).isoformat(),
        approval_reference=f"ticket-{assignment_id}",
        status=status,
        provenance={"test": True},
    )


def _att(
    att_id: str,
    att_type: AttestationType,
    identity: str,
    role: OperatorRole,
    *,
    expires_hours: int = 24,
    status: AttestationStatus = AttestationStatus.ACTIVE,
    revoked_ref: str | None = None,
) -> ActivationAttestation:
    now = _now()
    return ActivationAttestation(
        attestation_id=att_id,
        attestation_type=att_type,
        operator_identity=identity,
        operator_role=role,
        signed_timestamp=now.isoformat(),
        expiration_timestamp=(now + timedelta(hours=expires_hours)).isoformat(),
        evidence_references=("reports/paper_portfolio_activation_checklist_v1.md",),
        policy_version="paper-activation-policy-v1",
        status=status,
        revocation_reference=revoked_ref,
        provenance={"test": True},
    )


def _valid_roles() -> list[OperatorRoleAssignment]:
    return [
        _role("r1", "operator_alpha", OperatorRole.PAPER_OPERATOR),
        _role("r2", "approver_alpha", OperatorRole.PAPER_APPROVER),
        _role("r3", "risk_alpha", OperatorRole.RISK_REVIEWER),
        _role("r4", "admin_alpha", OperatorRole.SYSTEM_ADMIN),
        _role("r5", "incident_alpha", OperatorRole.INCIDENT_OWNER),
    ]


def _valid_attestations() -> list[ActivationAttestation]:
    pairs = [
        (AttestationType.RUNBOOK_REVIEWED, "approver_alpha", OperatorRole.PAPER_APPROVER),
        (AttestationType.BACKUP_POLICY_APPROVED, "risk_alpha", OperatorRole.RISK_REVIEWER),
        (AttestationType.RESTORE_TEST_APPROVED, "risk_alpha", OperatorRole.RISK_REVIEWER),
        (AttestationType.RECONCILIATION_POLICY_APPROVED, "risk_alpha", OperatorRole.RISK_REVIEWER),
        (AttestationType.CORPORATE_ACTION_PROCEDURE_APPROVED, "approver_alpha", OperatorRole.PAPER_APPROVER),
        (AttestationType.INCIDENT_RESPONSE_APPROVED, "incident_alpha", OperatorRole.INCIDENT_OWNER),
        (AttestationType.PAPER_ONLY_BOUNDARY_APPROVED, "approver_alpha", OperatorRole.PAPER_APPROVER),
        (AttestationType.NO_BROKER_ACCESS_CONFIRMED, "risk_alpha", OperatorRole.RISK_REVIEWER),
        (AttestationType.NO_PRODUCTION_PORTFOLIO_ACCESS_CONFIRMED, "risk_alpha", OperatorRole.RISK_REVIEWER),
        (AttestationType.MANUAL_APPROVAL_ONLY_CONFIRMED, "approver_alpha", OperatorRole.PAPER_APPROVER),
        (AttestationType.ACTIVATION_WINDOW_APPROVED, "approver_alpha", OperatorRole.PAPER_APPROVER),
    ]
    return [
        _att(f"a{i+1}", att_type, identity, role)
        for i, (att_type, identity, role) in enumerate(pairs)
    ]


def _evaluate(model: PaperActivationGateModel, *, roles=None, attestations=None, unresolved_warnings=None, **overrides):
    policy = PaperActivationPolicy.default()
    return model.evaluate(
        policy=policy,
        role_assignments=roles if roles is not None else _valid_roles(),
        attestations=attestations if attestations is not None else _valid_attestations(),
        requested_mode=overrides.get("requested_mode", "PAPER_MANUAL"),
        decision_timestamp=_now().isoformat(),
        runbook_version=overrides.get("runbook_version", "paper-ops-runbook-v1"),
        backup_cadence=overrides.get("backup_cadence", "daily"),
        restore_test_cadence=overrides.get("restore_test_cadence", "weekly"),
        reconciliation_cadence=overrides.get("reconciliation_cadence", "daily"),
        reporting_cadence=overrides.get("reporting_cadence", "daily"),
        escalation_contacts=overrides.get("escalation_contacts", {"incident_owner": "incident_alpha", "risk_reviewer": "risk_alpha"}),
        unresolved_warnings=unresolved_warnings if unresolved_warnings is not None else [],
        corporate_action_procedure_valid=overrides.get("corporate_action_procedure_valid", True),
        incident_response_procedure_valid=overrides.get("incident_response_procedure_valid", True),
        rollback_procedure_valid=overrides.get("rollback_procedure_valid", True),
        broker_access_attempted=overrides.get("broker_access_attempted", False),
        production_portfolio_access_attempted=overrides.get("production_portfolio_access_attempted", False),
        autonomous_approval_attempted=overrides.get("autonomous_approval_attempted", False),
    )


def test_activation_gate_allows_manual_paper_when_all_invariants_hold() -> None:
    model = PaperActivationGateModel(Path.cwd())
    decision = _evaluate(model)
    assert decision.activation_status is ActivationStatus.READY_FOR_MANUAL_PAPER
    assert decision.approved_mode == "PAPER_MANUAL"
    assert decision.blockers == ()
    assert "frozen_marker_hashes" in decision.satisfied_prerequisites


def test_activation_gate_fails_closed_on_missing_required_attestation() -> None:
    model = PaperActivationGateModel(Path.cwd())
    atts = [a for a in _valid_attestations() if a.attestation_type is not AttestationType.RESTORE_TEST_APPROVED]
    decision = _evaluate(model, attestations=atts)
    assert decision.activation_status is ActivationStatus.BLOCKED
    assert "MISSING_OR_EXPIRED_ATTESTATION" in decision.blockers


def test_activation_gate_blocks_on_role_overlap_rules() -> None:
    model = PaperActivationGateModel(Path.cwd())
    roles = [
        _role("r1", "operator_approver", OperatorRole.PAPER_OPERATOR),
        _role("r2", "operator_approver", OperatorRole.PAPER_APPROVER),
        _role("r3", "risk_alpha", OperatorRole.RISK_REVIEWER),
        _role("r4", "admin_alpha", OperatorRole.SYSTEM_ADMIN),
        _role("r5", "incident_alpha", OperatorRole.INCIDENT_OWNER),
    ]
    decision = _evaluate(model, roles=roles)
    assert "DUTY_SEPARATION_VIOLATION" in decision.blockers


def test_activation_gate_blocks_when_warning_limit_exceeded() -> None:
    model = PaperActivationGateModel(Path.cwd())
    decision = _evaluate(model, unresolved_warnings=["warning-1"])
    assert "UNRESOLVED_WARNING_LIMIT_EXCEEDED" in decision.blockers


def test_activation_gate_blocks_on_revoked_attestation() -> None:
    model = PaperActivationGateModel(Path.cwd())
    atts = _valid_attestations()
    revoked = _att(
        "a-revoked",
        AttestationType.RESTORE_TEST_APPROVED,
        "risk_alpha",
        OperatorRole.RISK_REVIEWER,
        status=AttestationStatus.REVOKED,
        revoked_ref="incident-123",
    )
    atts[2] = revoked
    decision = _evaluate(model, attestations=atts)
    assert "ATTESTATION_REVOKED" in decision.blockers


def test_activation_gate_revocation_changes_state_to_revoked() -> None:
    model = PaperActivationGateModel(Path.cwd())
    decision = _evaluate(model)
    revoked = model.revoke(
        prior_decision=decision,
        revocation_reasons=["MANUAL_REVOKE", "INCIDENT_REOPENED"],
        revoked_at_timestamp=(_now() + timedelta(hours=1)).isoformat(),
    )
    assert revoked.activation_status is ActivationStatus.REVOKED
    assert revoked.approved_mode == "BLOCKED"
    assert "MANUAL_REVOKE" in revoked.blockers


def test_activation_gate_blocks_on_manual_boundary_violations() -> None:
    model = PaperActivationGateModel(Path.cwd())
    decision = _evaluate(
        model,
        broker_access_attempted=True,
        production_portfolio_access_attempted=True,
        autonomous_approval_attempted=True,
    )
    assert "BROKER_ACCESS_ATTEMPTED" in decision.blockers
    assert "PRODUCTION_PORTFOLIO_ACCESS_ATTEMPTED" in decision.blockers
    assert "AUTONOMOUS_APPROVAL_ATTEMPTED" in decision.blockers


def test_activation_gate_policy_is_frozen_dataclass() -> None:
    policy = PaperActivationPolicy.default()
    with pytest.raises(FrozenInstanceError):
        policy.version = "mutated"  # type: ignore[misc]


def test_activation_gate_rejects_expired_role_assignments() -> None:
    model = PaperActivationGateModel(Path.cwd())
    roles = _valid_roles()
    roles[0] = _role("r1", "operator_alpha", OperatorRole.PAPER_OPERATOR, expires_hours=-1)
    decision = _evaluate(model, roles=roles)
    assert "MISSING_REQUIRED_ROLE_ASSIGNMENT" in decision.blockers


def test_activation_gate_marker_and_frozen_hash_drift_blocks_activation(tmp_path: Path) -> None:
    repo = tmp_path
    # Copy only required files then tamper marker hash.
    for rel in PaperActivationGateModel.FROZEN_HASHES:
        src = Path.cwd() / rel
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    for rel in PaperActivationGateModel.FROZEN_MARKER_HASHES:
        src = Path.cwd() / rel
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())

    marker_path = repo / "data/research/logs/PaperPortfolioOperationsReadiness_Validated.json"
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    payload["tampered"] = True
    marker_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    for report_name in (
        "paper_portfolio_corporate_action_procedure_v1.md",
        "paper_portfolio_incident_response_procedure_v1.md",
        "paper_portfolio_rollback_procedure_v1.md",
    ):
        src = Path.cwd() / "reports" / report_name
        dst = repo / "reports" / report_name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())

    model = PaperActivationGateModel(repo)
    decision = _evaluate(model)
    assert "MILESTONE_MARKER_DRIFT" in decision.blockers


def test_activation_gate_blocks_on_procedure_cadence_mismatch() -> None:
    model = PaperActivationGateModel(Path.cwd())
    decision = _evaluate(
        model,
        backup_cadence="weekly",
        restore_test_cadence="monthly",
        reconciliation_cadence="weekly",
        reporting_cadence="weekly",
        runbook_version="paper-ops-runbook-v2",
        corporate_action_procedure_valid=False,
        incident_response_procedure_valid=False,
        rollback_procedure_valid=False,
    )
    assert "BACKUP_CADENCE_MISSING" in decision.blockers
    assert "RESTORE_TEST_CADENCE_MISSING" in decision.blockers
    assert "RECONCILIATION_CADENCE_MISSING" in decision.blockers
    assert "REPORTING_CADENCE_MISSING" in decision.blockers
    assert "RUNBOOK_VERSION_MISMATCH" in decision.blockers
    assert "CORPORATE_ACTION_PROCEDURE_INVALID" in decision.blockers
    assert "INCIDENT_RESPONSE_PROCEDURE_INVALID" in decision.blockers
    assert "ROLLBACK_PROCEDURE_INVALID" in decision.blockers


def test_activation_gate_deterministic_decision_id() -> None:
    model = PaperActivationGateModel(Path.cwd())
    d1 = _evaluate(model)
    d2 = _evaluate(model)
    assert d1.decision_id == d2.decision_id
    assert d1.audit_reference == d2.audit_reference
