from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Iterable

from engine.phase3.approval import ApprovalState
from engine.phase3.contracts import PHASE2_SCHEMA_VERSION_CONTRACT
from engine.phase3.context import ResearchContext
from engine.phase3.expected_return.model import ExpectedReturnResult

from .types import BlockingCode, DecisionAudit, DecisionAuditStep


class DecisionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DecisionResult:
    ticker: str
    expected_annual_return: float
    confidence_adjusted_expected_return: float
    margin_of_safety: float
    research_confidence: float
    approval_status: ApprovalState
    decision_eligible: bool
    blocking_reasons: tuple[BlockingCode, ...]
    decision_audit: DecisionAudit


class DecisionModel:
    CONFIDENCE_THRESHOLD = 50.0
    MAX_ARTIFACT_AGE_HOURS = 72

    def evaluate(
        self,
        research_context: ResearchContext,
        expected_return: ExpectedReturnResult,
        *,
        reference_time: datetime | None = None,
    ) -> DecisionResult:
        if not isinstance(research_context, ResearchContext):
            raise DecisionValidationError("DecisionModel requires a ResearchContext input.")
        if not isinstance(expected_return, ExpectedReturnResult):
            raise DecisionValidationError("DecisionModel requires an ExpectedReturnResult input.")

        steps: list[DecisionAuditStep] = []
        blocking = set()
        timestamp = self._audit_timestamp(research_context)
        now = reference_time or self._parse_timestamp(research_context.artifact_metadata.get("generated_at")) or datetime(1970, 1, 1, tzinfo=timezone.utc)

        self._step_approval(research_context, steps, blocking, timestamp)
        self._step_expected_return_integrity(research_context, expected_return, steps, blocking, timestamp)
        self._step_research_context_integrity(research_context, steps, blocking, timestamp)
        self._step_artifact_integrity(research_context, steps, blocking, timestamp, now)
        self._step_confidence(research_context, steps, blocking, timestamp)

        blocking_codes = self._sorted_codes(blocking)
        decision_eligible = len(blocking_codes) == 0
        deterministic_record = {
            "ticker": research_context.ticker,
            "expected_annual_return": expected_return.expected_annual_return,
            "confidence_adjusted_expected_return": expected_return.confidence_adjusted_expected_return,
            "margin_of_safety": expected_return.margin_of_safety,
            "research_confidence": research_context.confidence,
            "approval_status": research_context.approval_status.value,
            "blocking_reasons": [code.value for code in blocking_codes],
            "expected_return_audit_hash": self._expected_return_hash(expected_return),
            "artifact_generated_at": str(research_context.artifact_metadata.get("generated_at") or ""),
            "artifact_schema_version": str(research_context.artifact_metadata.get("schema_version") or ""),
        }
        audit = DecisionAudit(
            ticker=research_context.ticker,
            approval_state=research_context.approval_status,
            blocking_reasons=blocking_codes,
            steps=tuple(steps),
            deterministic_record=deterministic_record,
        )

        return DecisionResult(
            ticker=research_context.ticker,
            expected_annual_return=expected_return.expected_annual_return,
            confidence_adjusted_expected_return=expected_return.confidence_adjusted_expected_return,
            margin_of_safety=expected_return.margin_of_safety,
            research_confidence=research_context.confidence,
            approval_status=research_context.approval_status,
            decision_eligible=decision_eligible,
            blocking_reasons=blocking_codes,
            decision_audit=audit,
        )

    def _step_approval(self, research_context: ResearchContext, steps: list[DecisionAuditStep], blocking: set[BlockingCode], timestamp: str) -> None:
        approved = research_context.approval_status is ApprovalState.APPROVED_FOR_EIPV
        if not approved:
            blocking.add(BlockingCode.NOT_APPROVED)
        steps.append(
            DecisionAuditStep(
                step="approval_status",
                passed=approved,
                detail=f"approval_status={research_context.approval_status.value}",
                timestamp=timestamp,
            )
        )

    def _step_expected_return_integrity(
        self,
        research_context: ResearchContext,
        expected_return: ExpectedReturnResult,
        steps: list[DecisionAuditStep],
        blocking: set[BlockingCode],
        timestamp: str,
    ) -> None:
        finite_values = (
            expected_return.expected_annual_return,
            expected_return.confidence_adjusted_expected_return,
            expected_return.margin_of_safety,
            expected_return.expected_intrinsic_value,
            expected_return.expected_volatility_estimate,
        )
        valid = (
            expected_return.ticker == research_context.ticker
            and bool(expected_return.calculation_audit)
            and all(value == value and value not in (float("inf"), float("-inf")) for value in finite_values)
        )
        if not valid:
            blocking.add(BlockingCode.INVALID_EXPECTED_RETURN)
        steps.append(
            DecisionAuditStep(
                step="expected_return_integrity",
                passed=valid,
                detail="ticker match, finite values, and immutable calculation audit",
                timestamp=timestamp,
                record={"audit_length": len(expected_return.calculation_audit)},
            )
        )

    def _step_research_context_integrity(
        self,
        research_context: ResearchContext,
        steps: list[DecisionAuditStep],
        blocking: set[BlockingCode],
        timestamp: str,
    ) -> None:
        required_metadata = ("available", "status", "generated_at", "schema_version", "phase2_framework_locked", "phase2_lock_name")
        missing = [key for key in required_metadata if key not in research_context.artifact_metadata]
        valid = not missing and bool(research_context.ticker)
        if not valid:
            blocking.add(BlockingCode.MISSING_REQUIRED_INPUT)
        steps.append(
            DecisionAuditStep(
                step="research_context_integrity",
                passed=valid,
                detail="required research metadata present",
                timestamp=timestamp,
                record={"missing": tuple(missing)},
            )
        )

    def _step_artifact_integrity(
        self,
        research_context: ResearchContext,
        steps: list[DecisionAuditStep],
        blocking: set[BlockingCode],
        timestamp: str,
        now: datetime,
    ) -> None:
        metadata = research_context.artifact_metadata
        available = bool(metadata.get("available")) and str(metadata.get("status") or "") == "valid"
        if not available:
            blocking.add(BlockingCode.INVALID_ARTIFACT)

        schema_match = str(metadata.get("schema_version") or "") == PHASE2_SCHEMA_VERSION_CONTRACT
        if not schema_match:
            blocking.add(BlockingCode.SCHEMA_MISMATCH)

        generated_at = self._parse_timestamp(metadata.get("generated_at"))
        is_stale = True
        if generated_at is not None:
            age_hours = (now - generated_at).total_seconds() / 3600.0
            is_stale = age_hours > self.MAX_ARTIFACT_AGE_HOURS
        if is_stale:
            blocking.add(BlockingCode.STALE_ARTIFACT)

        framework_ok = bool(metadata.get("phase2_framework_locked")) and bool(metadata.get("phase2_lock_name"))
        if not framework_ok:
            blocking.add(BlockingCode.VALIDATION_FAILURE)

        passed = available and schema_match and not is_stale and framework_ok
        steps.append(
            DecisionAuditStep(
                step="artifact_integrity",
                passed=passed,
                detail="adapter integrity checks for availability, schema, freshness, and lock metadata",
                timestamp=timestamp,
                record={
                    "available": available,
                    "schema_match": schema_match,
                    "is_stale": is_stale,
                    "framework_ok": framework_ok,
                },
            )
        )

    def _step_confidence(self, research_context: ResearchContext, steps: list[DecisionAuditStep], blocking: set[BlockingCode], timestamp: str) -> None:
        confidence_ok = float(research_context.confidence) >= self.CONFIDENCE_THRESHOLD
        if not confidence_ok:
            blocking.add(BlockingCode.LOW_CONFIDENCE)
        steps.append(
            DecisionAuditStep(
                step="research_confidence",
                passed=confidence_ok,
                detail=f"confidence={research_context.confidence:.2f}; threshold={self.CONFIDENCE_THRESHOLD:.2f}",
                timestamp=timestamp,
            )
        )

    @staticmethod
    def _sorted_codes(codes: Iterable[BlockingCode]) -> tuple[BlockingCode, ...]:
        order = {
            BlockingCode.NOT_APPROVED: 1,
            BlockingCode.LOW_CONFIDENCE: 2,
            BlockingCode.INVALID_EXPECTED_RETURN: 3,
            BlockingCode.INVALID_ARTIFACT: 4,
            BlockingCode.STALE_ARTIFACT: 5,
            BlockingCode.SCHEMA_MISMATCH: 6,
            BlockingCode.MISSING_REQUIRED_INPUT: 7,
            BlockingCode.VALIDATION_FAILURE: 8,
        }
        return tuple(sorted(codes, key=lambda code: order[code]))

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    @staticmethod
    def _audit_timestamp(research_context: ResearchContext) -> str:
        generated_at = str(research_context.artifact_metadata.get("generated_at") or "").strip()
        return generated_at or "deterministic"

    @staticmethod
    def _expected_return_hash(expected_return: ExpectedReturnResult) -> str:
        payload = (
            f"{expected_return.ticker}|{expected_return.bear_annualized_return:.12f}|"
            f"{expected_return.base_annualized_return:.12f}|{expected_return.bull_annualized_return:.12f}|"
            f"{expected_return.expected_annual_return:.12f}|{expected_return.expected_intrinsic_value:.12f}|"
            f"{expected_return.margin_of_safety:.12f}|{expected_return.expected_volatility_estimate:.12f}|"
            f"{expected_return.confidence_adjusted_expected_return:.12f}|{len(expected_return.calculation_audit)}"
        )
        return sha256(payload.encode("utf-8")).hexdigest()
