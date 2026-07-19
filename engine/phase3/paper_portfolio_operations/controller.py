from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from .preflight import PaperOperationsPreflightModel
from .types import (
    OperationType,
    OperationsMode,
    PaperOperationRequest,
    PaperOperationsPolicy,
    PaperOperationsSession,
    RequestStatus,
    SessionStatus,
)


class PaperOperationsControllerError(ValueError):
    pass


class PaperOperationsController:
    def __init__(self, *, policy: PaperOperationsPolicy, preflight_model: PaperOperationsPreflightModel) -> None:
        self.policy = policy
        self.preflight_model = preflight_model
        self.requests: list[PaperOperationRequest] = []

    def create_session(
        self,
        *,
        requested_mode: OperationsMode,
        operator_identity: str,
        operator_approval_reference: str,
        opened_timestamp: str,
    ) -> PaperOperationsSession:
        if requested_mode not in {
            OperationsMode.VALIDATION_ONLY,
            OperationsMode.PAPER_OBSERVATION,
            OperationsMode.PAPER_MANUAL,
        }:
            raise PaperOperationsControllerError("Unsupported session requested mode.")
        if requested_mode is OperationsMode.PAPER_MANUAL and not operator_approval_reference.strip():
            raise PaperOperationsControllerError("PAPER_MANUAL requires explicit operator approval reference.")

        session_id = self._deterministic_hash(
            {
                "type": "session",
                "requested_mode": requested_mode.value,
                "operator_identity": operator_identity,
                "operator_approval_reference": operator_approval_reference,
                "opened_timestamp": opened_timestamp,
                "policy_version": self.policy.version,
            }
        )
        audit_reference = self._deterministic_hash({"session_id": session_id, "audit": "v1"})
        return PaperOperationsSession(
            session_id=session_id,
            requested_mode=requested_mode,
            approved_mode=OperationsMode.VALIDATION_ONLY,
            operator_identity=operator_identity,
            operator_approval_reference=operator_approval_reference,
            preflight_result={},
            opened_timestamp=opened_timestamp,
            closed_timestamp=None,
            session_status=SessionStatus.CREATED,
            actions_attempted=0,
            actions_completed=0,
            actions_rejected=0,
            halt_reason=None,
            audit_reference=audit_reference,
        )

    def run_preflight(
        self,
        *,
        session: PaperOperationsSession,
        current_timestamp: str,
        latest_price_data_timestamp: str,
        recommendation_timestamps: Mapping[str, str],
        frozen_hashes: Mapping[str, str],
        backup_count: int,
        latest_restore_test_passed: bool,
        hygiene_passed: bool,
    ) -> PaperOperationsSession:
        preflight = self.preflight_model.evaluate(
            current_timestamp=current_timestamp,
            latest_price_data_timestamp=latest_price_data_timestamp,
            recommendation_timestamps=recommendation_timestamps,
            frozen_hashes=frozen_hashes,
            backup_count=backup_count,
            latest_restore_test_passed=latest_restore_test_passed,
            hygiene_passed=hygiene_passed,
            operator_approval_present=bool(session.operator_approval_reference.strip()),
        )
        status = SessionStatus.READY if preflight.passed else SessionStatus.PREFLIGHT_BLOCKED
        approved_mode = session.requested_mode
        if session.requested_mode is OperationsMode.PAPER_MANUAL and not session.operator_approval_reference.strip():
            approved_mode = OperationsMode.VALIDATION_ONLY
            status = SessionStatus.PREFLIGHT_BLOCKED

        return replace(
            session,
            approved_mode=approved_mode,
            preflight_result=asdict(preflight),
            session_status=status,
        )

    def open_session(self, *, session: PaperOperationsSession) -> PaperOperationsSession:
        if session.session_status is not SessionStatus.READY:
            raise PaperOperationsControllerError("Cannot open session unless preflight READY.")
        return replace(session, session_status=SessionStatus.ACTIVE)

    def record_operation_request(
        self,
        *,
        session: PaperOperationsSession,
        operation_type: OperationType,
        operator_identity: str,
        operator_approval_reference: str,
        requested_timestamp: str,
        effective_timestamp: str,
        source_audit_references: Mapping[str, str],
        recommendation_id: str | None = None,
        manual_approved: bool = False,
    ) -> tuple[PaperOperationsSession, PaperOperationRequest]:
        if session.session_status is not SessionStatus.ACTIVE:
            raise PaperOperationsControllerError("Session must be ACTIVE to record operation request.")
        if operation_type is OperationType.RECORD_PAPER_FILL and not manual_approved:
            request_status = RequestStatus.BLOCKED
            blockers = ("MANUAL_APPROVAL_REQUIRED_FOR_FILL",)
        elif operation_type is OperationType.RECORD_APPROVAL and not operator_approval_reference.strip():
            request_status = RequestStatus.BLOCKED
            blockers = ("APPROVAL_REFERENCE_REQUIRED",)
        else:
            request_status = RequestStatus.APPROVED_MANUALLY if manual_approved else RequestStatus.REQUESTED
            blockers = ()

        request_id = self._deterministic_hash(
            {
                "type": "operation_request",
                "session_id": session.session_id,
                "operation_type": operation_type.value,
                "recommendation_id": recommendation_id,
                "operator_identity": operator_identity,
                "operator_approval_reference": operator_approval_reference,
                "requested_timestamp": requested_timestamp,
                "effective_timestamp": effective_timestamp,
            }
        )
        request = PaperOperationRequest(
            request_id=request_id,
            session_id=session.session_id,
            operation_type=operation_type,
            recommendation_id=recommendation_id,
            operator_identity=operator_identity,
            operator_approval_reference=operator_approval_reference,
            requested_timestamp=requested_timestamp,
            effective_timestamp=effective_timestamp,
            source_audit_references=dict(source_audit_references),
            request_status=request_status,
            blocking_reasons=blockers,
            provenance={"policy_version": self.policy.version},
        )
        self.requests.append(request)

        completed_delta = 1 if request.request_status in {RequestStatus.APPROVED_MANUALLY, RequestStatus.COMPLETED} else 0
        rejected_delta = 1 if request.request_status in {RequestStatus.BLOCKED, RequestStatus.REJECTED, RequestStatus.FAILED} else 0
        updated_session = replace(
            session,
            actions_attempted=session.actions_attempted + 1,
            actions_completed=session.actions_completed + completed_delta,
            actions_rejected=session.actions_rejected + rejected_delta,
        )
        return updated_session, request

    def reject_operation_request(
        self,
        *,
        session: PaperOperationsSession,
        request: PaperOperationRequest,
        reasons: Sequence[str],
    ) -> tuple[PaperOperationsSession, PaperOperationRequest]:
        rejected = replace(request, request_status=RequestStatus.REJECTED, blocking_reasons=tuple(sorted(set(reasons))))
        self.requests.append(rejected)
        return (
            replace(
                session,
                actions_attempted=session.actions_attempted + 1,
                actions_rejected=session.actions_rejected + 1,
            ),
            rejected,
        )

    def halt_session(self, *, session: PaperOperationsSession, reason: str) -> PaperOperationsSession:
        return replace(session, session_status=SessionStatus.HALTED, approved_mode=OperationsMode.HALTED, halt_reason=reason)

    def close_session(self, *, session: PaperOperationsSession, closed_timestamp: str) -> PaperOperationsSession:
        if session.session_status is SessionStatus.HALTED:
            final_status = SessionStatus.HALTED
        elif session.session_status in {SessionStatus.ACTIVE, SessionStatus.READY}:
            final_status = SessionStatus.COMPLETED
        else:
            final_status = session.session_status
        return replace(session, session_status=final_status, closed_timestamp=closed_timestamp)

    def generate_operations_summary(self, *, session: PaperOperationsSession) -> Mapping[str, Any]:
        return {
            "session_id": session.session_id,
            "requested_mode": session.requested_mode.value,
            "approved_mode": session.approved_mode.value,
            "session_status": session.session_status.value,
            "actions_attempted": session.actions_attempted,
            "actions_completed": session.actions_completed,
            "actions_rejected": session.actions_rejected,
            "halt_reason": session.halt_reason,
            "request_count": len(self.requests),
            "blocked_requests": sum(1 for row in self.requests if row.request_status in {RequestStatus.BLOCKED, RequestStatus.REJECTED}),
            "audit_reference": session.audit_reference,
        }

    def _deterministic_hash(self, payload: Mapping[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(canonical.encode("utf-8")).hexdigest()
