from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import ast
import json
from typing import Any, Mapping, Sequence

from .types import (
    ActivationAttestation,
    ActivationStatus,
    AssignmentStatus,
    AttestationStatus,
    AttestationType,
    OperatorRole,
    OperatorRoleAssignment,
    PaperActivationDecision,
    PaperActivationPolicy,
)


class PaperActivationGateError(ValueError):
    pass


class PaperActivationGateModel:
    FROZEN_HASHES = {
        "config/research_os_manifest.json": "8133e50ecfad9dc31fc40d237c4409c4ca9573936603008b9f7ca30e3939a473",
        "engine/phase3/context.py": "2099134c8afee427adeb6b291b5f4e10c6b9f0fae9ca4313feb6018297e4c3f1",
        "engine/phase3/expected_return/model.py": "8e0d2b399872c6910bb242ccd204c3687cd7e817cc5138462d82981e1b73ceeb",
        "engine/phase3/decision_engine/model.py": "15f7a92d288314afbfcd1a2d19d1c1484bcd88beece2f8ce7aff4c3ead479beb",
        "engine/phase3/calibration/model.py": "e5977219a3abf15b34e69de0ceef05d6dfccae566934cafb77dd88156c1be367",
        "engine/phase3/portfolio_simulation/model.py": "a4565433daf6f3aa8a2673bd493f7265462109f93890b9f0c48b9965d213d385",
        "engine/phase3/shadow_portfolio_construction/model.py": "43d39d2fec949b6a6060741890e703f19341b2bce63ddce8bd6b481c37c9f53d",
        "engine/phase3/system_validation/model.py": "66b02a55a1cacf154035d9f9454eb4dc5a4c88836c525a49a68cd4de424da3ab",
        "engine/research_os_release.py": "bebb46337f73450af766b325eb6052a5a5db2276926e5166271b0be774f20a35",
        "engine/phase2_downstream.py": "7d25d7aa24be4177118ac41e209fc173e5e5c20607052a0ce4522352ad41804b",
        "engine/portfolio_engine.py": "4d39683c3a0fee762bf028f748216388aef5b68ed3b5ac149478f6e2f8afb63b",
    }

    FROZEN_MARKER_HASHES = {
        "data/research/logs/PaperPortfolioPersistenceReplay_Validated.json": "79883d7262cf7063206b85be149165f57db6ce7a3dc7a926531f4455ed6078cc",
        "data/research/logs/PaperPortfolioOperationsReadiness_Validated.json": "6ec1f1fc91644b346c271e7caa67a1ca472296ce6cc1f6cf7d2db1a3f3d31aa8",
        "data/research/logs/IndependentSystemCertification_Validated.json": "d47f21baa08eff6e14544ec316a04622b029dcf5a8b91a57cb648c3e4e8ac257",
    }

    REQUIRED_ATTESTATIONS = (
        AttestationType.RUNBOOK_REVIEWED,
        AttestationType.BACKUP_POLICY_APPROVED,
        AttestationType.RESTORE_TEST_APPROVED,
        AttestationType.RECONCILIATION_POLICY_APPROVED,
        AttestationType.CORPORATE_ACTION_PROCEDURE_APPROVED,
        AttestationType.INCIDENT_RESPONSE_APPROVED,
        AttestationType.PAPER_ONLY_BOUNDARY_APPROVED,
        AttestationType.NO_BROKER_ACCESS_CONFIRMED,
        AttestationType.NO_PRODUCTION_PORTFOLIO_ACCESS_CONFIRMED,
        AttestationType.MANUAL_APPROVAL_ONLY_CONFIRMED,
        AttestationType.ACTIVATION_WINDOW_APPROVED,
    )

    FORBIDDEN_IMPORT_PREFIXES = (
        "alpaca",
        "schwab",
        "ib_insync",
        "ccxt",
    )

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root)

    def evaluate(
        self,
        *,
        policy: PaperActivationPolicy,
        role_assignments: Sequence[OperatorRoleAssignment],
        attestations: Sequence[ActivationAttestation],
        requested_mode: str,
        decision_timestamp: str,
        runbook_version: str,
        backup_cadence: str,
        restore_test_cadence: str,
        reconciliation_cadence: str,
        reporting_cadence: str,
        escalation_contacts: Mapping[str, str],
        unresolved_warnings: Sequence[str],
        corporate_action_procedure_valid: bool,
        incident_response_procedure_valid: bool,
        rollback_procedure_valid: bool,
        broker_access_attempted: bool = False,
        production_portfolio_access_attempted: bool = False,
        autonomous_approval_attempted: bool = False,
    ) -> PaperActivationDecision:
        policy.validate()
        blockers: list[str] = []
        warnings: list[str] = []
        satisfied: list[str] = []

        now = self._parse_timestamp(decision_timestamp)

        if requested_mode.upper() not in {"VALIDATION_ONLY", "PAPER_OBSERVATION", "PAPER_MANUAL"}:
            blockers.append("UNSUPPORTED_REQUESTED_MODE")

        marker_refs = self._validate_markers()
        if len(marker_refs) == len(policy.required_milestone_markers):
            satisfied.append("required_milestones")
        else:
            blockers.append("REQUIRED_MILESTONE_MISSING_OR_INVALID")

        if self._validate_frozen_hashes(self.FROZEN_HASHES):
            satisfied.append("frozen_hashes")
        else:
            blockers.append("FROZEN_HASH_MISMATCH")

        if self._validate_frozen_hashes(self.FROZEN_MARKER_HASHES):
            satisfied.append("frozen_marker_hashes")
        else:
            blockers.append("MILESTONE_MARKER_DRIFT")

        active_roles = [r for r in role_assignments if r.status is AssignmentStatus.ACTIVE and self._parse_timestamp(r.expiration_timestamp) > now]
        if self._required_roles_assigned(active_roles, policy.required_operator_roles):
            satisfied.append("required_roles")
        else:
            blockers.append("MISSING_REQUIRED_ROLE_ASSIGNMENT")

        if self._duty_separation_ok(active_roles, policy.prohibited_role_overlap_rules):
            satisfied.append("duty_separation")
        else:
            blockers.append("DUTY_SEPARATION_VIOLATION")

        if self._minimum_independent_approvers_ok(active_roles, policy.minimum_independent_approvers):
            satisfied.append("minimum_independent_approvers")
        else:
            blockers.append("INSUFFICIENT_INDEPENDENT_APPROVERS")

        active_attestations = [a for a in attestations if a.status is AttestationStatus.ACTIVE and self._parse_timestamp(a.expiration_timestamp) > now]
        if self._required_attestations_present(active_attestations):
            satisfied.append("required_attestations")
        else:
            blockers.append("MISSING_OR_EXPIRED_ATTESTATION")

        if any(a.status is AttestationStatus.REVOKED for a in attestations):
            blockers.append("ATTESTATION_REVOKED")

        if runbook_version == policy.required_runbook_version:
            satisfied.append("runbook_version")
        else:
            blockers.append("RUNBOOK_VERSION_MISMATCH")

        if backup_cadence == policy.required_backup_cadence:
            satisfied.append("backup_cadence")
        else:
            blockers.append("BACKUP_CADENCE_MISSING")

        if restore_test_cadence == policy.required_restore_test_cadence:
            satisfied.append("restore_test_cadence")
        else:
            blockers.append("RESTORE_TEST_CADENCE_MISSING")

        if reconciliation_cadence == policy.required_reconciliation_cadence:
            satisfied.append("reconciliation_cadence")
        else:
            blockers.append("RECONCILIATION_CADENCE_MISSING")

        if reporting_cadence == policy.required_reporting_cadence:
            satisfied.append("reporting_cadence")
        else:
            blockers.append("REPORTING_CADENCE_MISSING")

        if self._escalation_contacts_assigned(policy.required_escalation_contacts, escalation_contacts):
            satisfied.append("escalation_contacts")
        else:
            blockers.append("ESCALATION_CONTACTS_MISSING")

        if corporate_action_procedure_valid and (self.repo_root / policy.required_corporate_action_procedure).exists():
            satisfied.append("corporate_action_procedure")
        else:
            blockers.append("CORPORATE_ACTION_PROCEDURE_INVALID")

        if incident_response_procedure_valid and (self.repo_root / policy.required_incident_response_procedure).exists():
            satisfied.append("incident_response_procedure")
        else:
            blockers.append("INCIDENT_RESPONSE_PROCEDURE_INVALID")

        if rollback_procedure_valid and (self.repo_root / policy.required_rollback_procedure).exists():
            satisfied.append("rollback_procedure")
        else:
            blockers.append("ROLLBACK_PROCEDURE_INVALID")

        if self._paper_only_boundaries_acknowledged(active_attestations):
            satisfied.append("paper_only_boundaries")
        else:
            blockers.append("PAPER_ONLY_BOUNDARY_NOT_ACKNOWLEDGED")

        if self._scan_forbidden_access_paths():
            satisfied.append("forbidden_access_scan")
        else:
            blockers.append("FORBIDDEN_ACCESS_PATH_DETECTED")

        if broker_access_attempted:
            blockers.append("BROKER_ACCESS_ATTEMPTED")
        if production_portfolio_access_attempted:
            blockers.append("PRODUCTION_PORTFOLIO_ACCESS_ATTEMPTED")
        if autonomous_approval_attempted:
            blockers.append("AUTONOMOUS_APPROVAL_ATTEMPTED")

        if len(unresolved_warnings) > policy.maximum_unresolved_warnings:
            blockers.append("UNRESOLVED_WARNING_LIMIT_EXCEEDED")
        warnings.extend(unresolved_warnings)

        expiration = now + timedelta(hours=policy.activation_expiration_period_hours)
        if expiration <= now:
            blockers.append("INVALID_EXPIRATION_TIMESTAMP")

        if any(a.status is AssignmentStatus.EXPIRED for a in role_assignments):
            blockers.append("EXPIRED_ROLE_ASSIGNMENT")

        activation_status = ActivationStatus.BLOCKED
        approved_mode = "BLOCKED"
        if not blockers:
            activation_status = ActivationStatus.READY_FOR_MANUAL_PAPER
            approved_mode = "PAPER_MANUAL"

        decision_payload = {
            "requested_mode": requested_mode,
            "approved_mode": approved_mode,
            "activation_status": activation_status.value,
            "decision_timestamp": decision_timestamp,
            "satisfied_prerequisites": sorted(set(satisfied)),
            "blockers": sorted(set(blockers)),
            "warnings": sorted(set(warnings)),
            "approvers": sorted({r.operator_identity for r in active_roles if r.role in {OperatorRole.PAPER_APPROVER, OperatorRole.RISK_REVIEWER}}),
            "role_assignments": sorted(r.assignment_id for r in role_assignments),
            "attestations": sorted(a.attestation_id for a in attestations),
            "milestones": sorted(marker_refs),
            "policy_version": policy.version,
        }
        decision_id = sha256(json.dumps(decision_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        audit_reference = sha256(json.dumps({"decision_id": decision_id, "audit": "activation-gate-v1"}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

        return PaperActivationDecision(
            decision_id=decision_id,
            decision_timestamp=decision_timestamp,
            requested_mode=requested_mode,
            approved_mode=approved_mode,
            activation_status=activation_status,
            expiration_timestamp=expiration.isoformat(),
            satisfied_prerequisites=tuple(sorted(set(satisfied))),
            blockers=tuple(sorted(set(blockers))),
            warnings=tuple(sorted(set(warnings))),
            approver_identities=tuple(sorted({r.operator_identity for r in active_roles if r.role in {OperatorRole.PAPER_APPROVER, OperatorRole.RISK_REVIEWER}})),
            role_assignments=tuple(sorted(r.assignment_id for r in role_assignments)),
            attestation_references=tuple(sorted(a.attestation_id for a in attestations)),
            milestone_references=tuple(sorted(marker_refs)),
            audit_reference=audit_reference,
            provenance={"policy_version": policy.version, "manual_activation_only": True},
        )

    def revoke(
        self,
        *,
        prior_decision: PaperActivationDecision,
        revocation_reasons: Sequence[str],
        revoked_at_timestamp: str,
    ) -> PaperActivationDecision:
        reasons = tuple(sorted(set(revocation_reasons)))
        status = ActivationStatus.REVOKED if reasons else prior_decision.activation_status
        payload = {**asdict(prior_decision), "revoked_at": revoked_at_timestamp, "reasons": reasons}
        new_id = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
        return PaperActivationDecision(
            decision_id=new_id,
            decision_timestamp=revoked_at_timestamp,
            requested_mode=prior_decision.requested_mode,
            approved_mode="BLOCKED" if reasons else prior_decision.approved_mode,
            activation_status=status,
            expiration_timestamp=prior_decision.expiration_timestamp,
            satisfied_prerequisites=prior_decision.satisfied_prerequisites,
            blockers=tuple(sorted(set(prior_decision.blockers + reasons))),
            warnings=prior_decision.warnings,
            approver_identities=prior_decision.approver_identities,
            role_assignments=prior_decision.role_assignments,
            attestation_references=prior_decision.attestation_references,
            milestone_references=prior_decision.milestone_references,
            audit_reference=prior_decision.audit_reference,
            provenance={**dict(prior_decision.provenance), "revoked": bool(reasons)},
        )

    def _validate_markers(self) -> tuple[str, ...]:
        valid: list[str] = []
        for rel in PaperActivationPolicy.default().required_milestone_markers:
            path = self.repo_root / rel
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if payload.get("milestone") and payload.get("recorded_at"):
                valid.append(rel)
        return tuple(sorted(valid))

    def _validate_frozen_hashes(self, expected_hashes: Mapping[str, str]) -> bool:
        for rel, expected in expected_hashes.items():
            path = self.repo_root / rel
            if not path.exists():
                return False
            actual = sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                return False
        return True

    def _required_roles_assigned(self, roles: Sequence[OperatorRoleAssignment], required: Sequence[OperatorRole]) -> bool:
        assigned = {row.role for row in roles}
        return set(required).issubset(assigned)

    def _duty_separation_ok(self, roles: Sequence[OperatorRoleAssignment], overlap_rules: Mapping[str, tuple[OperatorRole, ...]]) -> bool:
        by_identity: dict[str, set[OperatorRole]] = {}
        for row in roles:
            by_identity.setdefault(row.operator_identity, set()).add(row.role)
        for assigned in by_identity.values():
            for rule in overlap_rules.values():
                if set(rule).issubset(assigned):
                    return False
        return True

    def _minimum_independent_approvers_ok(self, roles: Sequence[OperatorRoleAssignment], minimum: int) -> bool:
        identities = {
            row.operator_identity
            for row in roles
            if row.role in {OperatorRole.PAPER_APPROVER, OperatorRole.RISK_REVIEWER}
        }
        return len(identities) >= minimum

    def _required_attestations_present(self, attestations: Sequence[ActivationAttestation]) -> bool:
        by_type = {row.attestation_type for row in attestations}
        return set(self.REQUIRED_ATTESTATIONS).issubset(by_type)

    def _escalation_contacts_assigned(self, required_keys: Sequence[str], contacts: Mapping[str, str]) -> bool:
        for key in required_keys:
            if not contacts.get(key, "").strip():
                return False
        return True

    def _paper_only_boundaries_acknowledged(self, attestations: Sequence[ActivationAttestation]) -> bool:
        needed = {
            AttestationType.PAPER_ONLY_BOUNDARY_APPROVED,
            AttestationType.NO_BROKER_ACCESS_CONFIRMED,
            AttestationType.NO_PRODUCTION_PORTFOLIO_ACCESS_CONFIRMED,
            AttestationType.MANUAL_APPROVAL_ONLY_CONFIRMED,
        }
        seen = {row.attestation_type for row in attestations}
        return needed.issubset(seen)

    def _scan_forbidden_access_paths(self) -> bool:
        root = self.repo_root / "engine" / "phase3" / "paper_portfolio_activation_gate"
        forbidden_calls = {"open_session", "record_paper_fill"}
        for py_file in root.rglob("*.py"):
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(self.FORBIDDEN_IMPORT_PREFIXES):
                            return False
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith(self.FORBIDDEN_IMPORT_PREFIXES):
                        return False
                if isinstance(node, ast.Call):
                    func_name = None
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr
                    if func_name in forbidden_calls:
                        return False
        return True

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        return datetime.fromisoformat(value)
