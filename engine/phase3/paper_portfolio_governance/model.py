from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from engine.phase3.calibration.model import CalibrationResult
from engine.phase3.decision_engine.model import DecisionResult
from engine.phase3.expected_return.model import ExpectedReturnResult
from engine.phase3.portfolio_simulation.model import SimulationResult
from engine.phase3.shadow_portfolio_construction.model import ShadowAllocationResult

from .policy import PaperPolicyValidationError, PaperRecommendationPolicy
from .types import (
    GovernanceAudit,
    GovernanceValidationStep,
    PaperGovernanceResult,
    PaperPortfolioState,
    PaperRecommendationRecord,
    PaperRecommendationStatus,
)


class PaperGovernanceValidationError(ValueError):
    pass


class PaperRecommendationModel:
    SOURCE_MODULES = (
        "engine.phase3.decision_engine.model",
        "engine.phase3.expected_return.model",
        "engine.phase3.calibration.model",
        "engine.phase3.portfolio_simulation.model",
        "engine.phase3.shadow_portfolio_construction.model",
        "engine.phase3.paper_portfolio_governance.policy",
        "engine.phase3.paper_portfolio_governance.types",
        "engine.phase3.paper_portfolio_governance.model",
    )

    def evaluate(
        self,
        *,
        decision_results: Sequence[DecisionResult],
        expected_return_results: Mapping[str, ExpectedReturnResult],
        calibration_results: Mapping[str, CalibrationResult],
        simulation_result: SimulationResult,
        shadow_allocation_result: ShadowAllocationResult,
        policy: PaperRecommendationPolicy,
        paper_portfolio_state: PaperPortfolioState,
        human_approvals: Mapping[str, tuple[str, ...]] | None = None,
        as_of_timestamp: str = "deterministic",
        source_artifacts_valid: bool = True,
        source_schema_compatible: bool = True,
        source_audits_valid: bool = True,
        production_portfolio_access_attempted: bool = False,
        broker_access_attempted: bool = False,
        live_execution_language_present: bool = False,
    ) -> PaperGovernanceResult:
        steps: list[GovernanceValidationStep] = []
        self._fail_closed_guards(
            source_artifacts_valid=source_artifacts_valid,
            source_schema_compatible=source_schema_compatible,
            source_audits_valid=source_audits_valid,
            production_portfolio_access_attempted=production_portfolio_access_attempted,
            broker_access_attempted=broker_access_attempted,
            live_execution_language_present=live_execution_language_present,
        )
        policy.validate()

        if not decision_results:
            raise PaperGovernanceValidationError("decision_results are required.")
        if not expected_return_results:
            raise PaperGovernanceValidationError("expected_return_results are required.")
        if not calibration_results:
            raise PaperGovernanceValidationError("calibration_results are required.")

        steps.append(
            GovernanceValidationStep(
                step="input_contract_validation",
                passed=True,
                detail="All required source objects are present.",
                timestamp=as_of_timestamp,
            )
        )

        proposed_weights = dict(shadow_allocation_result.proposed_target_weights)
        cash_weight = float(shadow_allocation_result.proposed_cash_weight)
        self._validate_weight_reconciliation(proposed_weights, cash_weight)

        approvals = {k.upper(): set(v) for k, v in (human_approvals or {}).items()}
        blocked_recommendations: list[str] = []
        blocking_map: dict[str, tuple[str, ...]] = {}
        status_map: dict[str, PaperRecommendationStatus] = {}
        records: list[PaperRecommendationRecord] = []
        eligibility_checks: dict[str, bool] = {}

        for decision in sorted(decision_results, key=lambda row: row.ticker):
            ticker = decision.ticker.upper()
            if ticker not in expected_return_results or ticker not in calibration_results:
                raise PaperGovernanceValidationError(f"Missing required source output for {ticker}.")

            expected = expected_return_results[ticker]
            calibration = calibration_results[ticker]
            reasons = self._ticker_blocking_reasons(
                ticker=ticker,
                decision=decision,
                expected=expected,
                calibration=calibration,
                policy=policy,
                simulation=simulation_result,
                shadow=shadow_allocation_result,
                created_timestamp=as_of_timestamp,
            )
            current_weight = float(paper_portfolio_state.paper_weights.get(ticker, 0.0))
            proposed_weight = float(proposed_weights.get(ticker, 0.0))

            if reasons:
                proposed_weight = 0.0
                blocked_recommendations.append(ticker)

            rec_type = self._recommendation_type(current_weight=current_weight, proposed_weight=proposed_weight)
            if rec_type not in policy.allowed_recommendation_types:
                reasons.append("RECOMMENDATION_TYPE_NOT_ALLOWED")
                proposed_weight = 0.0

            stale = self._is_stale(decision, as_of_timestamp, policy.maximum_recommendation_age_hours)
            has_approvals = set(policy.required_approvals).issubset(approvals.get(ticker, set()))
            status = self._status_from_checks(reasons=tuple(reasons), stale=stale, has_required_approvals=has_approvals)

            if status is PaperRecommendationStatus.APPROVED_FOR_PAPER and not has_approvals:
                raise PaperGovernanceValidationError("Autonomous approval is not allowed.")
            if status is PaperRecommendationStatus.EXPIRED and has_approvals:
                # Explicitly enforce expiration precedence over approval.
                status = PaperRecommendationStatus.EXPIRED

            recommendation_id = self._recommendation_id(
                ticker=ticker,
                recommendation_type=rec_type,
                current_weight=current_weight,
                proposed_weight=proposed_weight,
                expected_return=expected.expected_annual_return,
                confidence_adjusted_return=expected.confidence_adjusted_expected_return,
                created_timestamp=as_of_timestamp,
                policy_version=policy.version,
            )

            expiration = self._expiration_timestamp(as_of_timestamp, policy.maximum_recommendation_age_hours)
            record = PaperRecommendationRecord(
                recommendation_id=recommendation_id,
                ticker=ticker,
                recommendation_type=rec_type,
                current_paper_weight=current_weight,
                proposed_paper_weight=proposed_weight,
                expected_return=expected.expected_annual_return,
                confidence_adjusted_return=expected.confidence_adjusted_expected_return,
                confidence=decision.research_confidence,
                decision_eligibility=decision.decision_eligible,
                policy_status="passed" if not reasons else "blocked",
                blocking_reasons=tuple(sorted(set(reasons))),
                source_audit_references={
                    "decision": self._decision_reference(decision),
                    "expected_return": self._expected_return_reference(expected),
                    "calibration": self._calibration_reference(calibration),
                    "simulation": simulation_result.simulation_audit.configuration_hash,
                    "shadow": shadow_allocation_result.audit.configuration_hash,
                },
                created_timestamp=as_of_timestamp,
                expiration_timestamp=expiration,
                status=status,
            )
            records.append(record)
            blocking_map[ticker] = record.blocking_reasons
            status_map[ticker] = status
            eligibility_checks[ticker] = decision.decision_eligible and expected.ticker == ticker

        final_weights = {
            row.ticker: row.proposed_paper_weight
            for row in records
            if row.status in (PaperRecommendationStatus.PENDING_APPROVAL, PaperRecommendationStatus.APPROVED_FOR_PAPER)
        }
        cash_after = max(0.0, 1.0 - sum(final_weights.values()))

        policy_checks = {
            "cash_reserve": cash_after >= policy.minimum_cash_reserve,
            "max_holdings": len(final_weights) <= policy.maximum_number_of_holdings,
            "max_position": all(weight <= policy.maximum_position_weight + 1e-12 for weight in final_weights.values()),
            "max_turnover": simulation_result.turnover <= policy.maximum_portfolio_turnover + 1e-12,
        }

        portfolio_blockers = tuple(sorted(key.upper() for key, passed in policy_checks.items() if not passed))
        if portfolio_blockers:
            blocked_records: list[PaperRecommendationRecord] = []
            for row in records:
                if row.status is PaperRecommendationStatus.EXPIRED:
                    blocked_records.append(row)
                    continue
                reasons = tuple(sorted(set(row.blocking_reasons + tuple(f"PORTFOLIO_POLICY_{name}" for name in portfolio_blockers))))
                blocked_records.append(
                    replace(
                        row,
                        proposed_paper_weight=0.0,
                        policy_status="blocked",
                        blocking_reasons=reasons,
                        status=PaperRecommendationStatus.BLOCKED,
                    )
                )
            records = blocked_records
            blocked_recommendations = sorted({row.ticker for row in records if row.status is PaperRecommendationStatus.BLOCKED})
            blocking_map = {row.ticker: row.blocking_reasons for row in records}
            status_map = {row.ticker: row.status for row in records}
            final_weights = {
                row.ticker: row.proposed_paper_weight
                for row in records
                if row.status in (PaperRecommendationStatus.PENDING_APPROVAL, PaperRecommendationStatus.APPROVED_FOR_PAPER)
            }
            cash_after = max(0.0, 1.0 - sum(final_weights.values()))

        steps.extend(
            (
                GovernanceValidationStep(
                    step="recommendation_evaluation",
                    passed=True,
                    detail="Per-ticker eligibility and policy checks completed.",
                    timestamp=as_of_timestamp,
                    record={"recommendation_count": len(records), "blocked_count": len(blocked_recommendations)},
                ),
                GovernanceValidationStep(
                    step="approval_enforcement",
                    passed=True,
                    detail="No automatic approval occurred; required approvals enforced.",
                    timestamp=as_of_timestamp,
                ),
                GovernanceValidationStep(
                    step="portfolio_reconciliation",
                    passed=True,
                    detail="Proposed paper target weights and cash weight reconcile.",
                    timestamp=as_of_timestamp,
                    record={"cash_weight": cash_after, "weight_sum": sum(final_weights.values())},
                ),
            )
        )

        input_hashes = {
            "decision": self._hash_payload([asdict(row) for row in decision_results]),
            "expected_return": self._hash_payload([asdict(expected_return_results[key]) for key in sorted(expected_return_results)]),
            "calibration": self._hash_payload([asdict(calibration_results[key]) for key in sorted(calibration_results)]),
            "simulation": self._hash_payload(asdict(simulation_result)),
            "shadow": self._hash_payload(asdict(shadow_allocation_result)),
            "paper_state": self._hash_payload(asdict(paper_portfolio_state)),
            "policy": self._hash_payload(asdict(policy)),
        }

        deterministic_record = {
            "tickers": tuple(row.ticker for row in records),
            "recommendation_ids": tuple(row.recommendation_id for row in records),
            "statuses": tuple(row.status.value for row in records),
            "policy_version": policy.version,
        }

        config_hash = self._hash_payload(
            {
                "input_hashes": input_hashes,
                "deterministic_record": deterministic_record,
                "required_approvals": policy.required_approvals,
                "as_of_timestamp": as_of_timestamp,
            }
        )

        audit = GovernanceAudit(
            source_modules=self.SOURCE_MODULES,
            policy_version=policy.version,
            input_hashes=input_hashes,
            validation_steps=tuple(steps),
            eligibility_checks=eligibility_checks,
            policy_checks=policy_checks,
            rejected_recommendations=tuple(sorted(blocked_recommendations)),
            blocking_reasons=blocking_map,
            approval_requirements=policy.required_approvals,
            configuration_hash=config_hash,
            deterministic_execution_record=deterministic_record,
            timestamp_metadata={"as_of": as_of_timestamp, "created": as_of_timestamp},
        )

        return PaperGovernanceResult(
            recommendation_records=tuple(records),
            proposed_paper_target_weights=dict(sorted(final_weights.items())),
            proposed_paper_cash_weight=cash_after,
            policy_checks=policy_checks,
            eligibility_checks=eligibility_checks,
            blocking_reasons=blocking_map,
            recommendation_status=status_map,
            governance_audit=audit,
        )

    @staticmethod
    def _validate_weight_reconciliation(weights: Mapping[str, float], cash_weight: float) -> None:
        if any(value < 0.0 for value in weights.values()) or cash_weight < 0.0:
            raise PaperGovernanceValidationError("Proposed weights must be non-negative.")
        total = sum(weights.values()) + cash_weight
        if abs(total - 1.0) > 1e-8:
            raise PaperGovernanceValidationError("Proposed weights do not reconcile to 1.0.")

    @staticmethod
    def _fail_closed_guards(
        *,
        source_artifacts_valid: bool,
        source_schema_compatible: bool,
        source_audits_valid: bool,
        production_portfolio_access_attempted: bool,
        broker_access_attempted: bool,
        live_execution_language_present: bool,
    ) -> None:
        if not source_artifacts_valid:
            raise PaperGovernanceValidationError("Source artifact missing or invalid.")
        if not source_schema_compatible:
            raise PaperGovernanceValidationError("Source schema is incompatible.")
        if not source_audits_valid:
            raise PaperGovernanceValidationError("Source audit is invalid.")
        if production_portfolio_access_attempted:
            raise PaperGovernanceValidationError("Production portfolio access is not permitted.")
        if broker_access_attempted:
            raise PaperGovernanceValidationError("Broker access is not permitted.")
        if live_execution_language_present:
            raise PaperGovernanceValidationError("Live execution language or objects are not permitted.")

    def _ticker_blocking_reasons(
        self,
        *,
        ticker: str,
        decision: DecisionResult,
        expected: ExpectedReturnResult,
        calibration: CalibrationResult,
        policy: PaperRecommendationPolicy,
        simulation: SimulationResult,
        shadow: ShadowAllocationResult,
        created_timestamp: str,
    ) -> list[str]:
        reasons: list[str] = []

        if policy.minimum_decision_eligibility and not decision.decision_eligible:
            reasons.append("DECISION_NOT_ELIGIBLE")
        if expected.expected_annual_return < policy.minimum_expected_return:
            reasons.append("EXPECTED_RETURN_BELOW_POLICY")
        if decision.research_confidence < policy.minimum_confidence:
            reasons.append("CONFIDENCE_BELOW_POLICY")
        if ticker in {item.upper() for item in policy.prohibited_tickers}:
            reasons.append("PROHIBITED_TICKER")

        if calibration.measurable is False and "MEASURABLE_ONLY" in policy.calibration_requirements:
            reasons.append("CALIBRATION_NOT_MEASURABLE")

        if "POSITIVE_CAGR" in policy.simulation_requirements and simulation.simulated_cagr <= 0:
            reasons.append("SIMULATION_CAGR_NON_POSITIVE")
        if "NON_NEGATIVE_CASH_UTILIZATION" in policy.simulation_requirements and simulation.cash_utilization < 0:
            reasons.append("SIMULATION_CASH_UTILIZATION_INVALID")

        if "WEIGHTS_RECONCILE" in policy.shadow_allocation_requirements:
            total = sum(shadow.proposed_target_weights.values()) + shadow.proposed_cash_weight
            if abs(total - 1.0) > 1e-8:
                reasons.append("SHADOW_WEIGHTS_NOT_RECONCILED")
        if "NO_CONSTRAINT_VIOLATIONS" in policy.shadow_allocation_requirements and shadow.constraint_violations:
            reasons.append("SHADOW_CONSTRAINT_VIOLATION")

        if self._is_stale(decision, created_timestamp, policy.maximum_recommendation_age_hours):
            reasons.append("RECOMMENDATION_STALE")

        return reasons

    @staticmethod
    def _decision_reference(decision: DecisionResult) -> str:
        payload = [
            decision.ticker,
            str(decision.decision_eligible),
            f"{decision.expected_annual_return:.12f}",
            f"{decision.confidence_adjusted_expected_return:.12f}",
            decision.approval_status.value,
        ]
        return sha256("|".join(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _expected_return_reference(expected: ExpectedReturnResult) -> str:
        payload = [
            expected.ticker,
            f"{expected.expected_annual_return:.12f}",
            f"{expected.confidence_adjusted_expected_return:.12f}",
            f"{expected.margin_of_safety:.12f}",
        ]
        return sha256("|".join(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _calibration_reference(calibration: CalibrationResult) -> str:
        payload = [
            calibration.ticker,
            calibration.measurement_state,
            str(calibration.measurable),
            str(calibration.forecast_error),
        ]
        return sha256("|".join(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _status_from_checks(
        *,
        reasons: tuple[str, ...],
        stale: bool,
        has_required_approvals: bool,
    ) -> PaperRecommendationStatus:
        if stale:
            return PaperRecommendationStatus.EXPIRED
        if reasons:
            return PaperRecommendationStatus.BLOCKED
        if not has_required_approvals:
            return PaperRecommendationStatus.PENDING_APPROVAL
        return PaperRecommendationStatus.APPROVED_FOR_PAPER

    @staticmethod
    def _recommendation_type(*, current_weight: float, proposed_weight: float) -> str:
        if proposed_weight > current_weight and current_weight == 0.0:
            return "INITIATE_POSITION"
        if proposed_weight > current_weight:
            return "INCREASE_WEIGHT"
        if proposed_weight < current_weight and proposed_weight == 0.0:
            return "EXIT_POSITION"
        if proposed_weight < current_weight:
            return "DECREASE_WEIGHT"
        if proposed_weight == current_weight and proposed_weight == 0.0:
            return "HOLD"
        return "REBALANCE"

    @staticmethod
    def _parse_ts(value: str) -> datetime | None:
        if not value or value == "deterministic":
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    def _is_stale(self, decision: DecisionResult, created_timestamp: str, max_age_hours: int) -> bool:
        generated_at = str(decision.decision_audit.deterministic_record.get("artifact_generated_at") or "")
        gts = self._parse_ts(generated_at)
        cts = self._parse_ts(created_timestamp)
        if gts is None or cts is None:
            return False
        age_hours = (cts - gts).total_seconds() / 3600.0
        return age_hours > max_age_hours

    @staticmethod
    def _expiration_timestamp(created_timestamp: str, max_age_hours: int) -> str:
        cts = PaperRecommendationModel._parse_ts(created_timestamp)
        if cts is None:
            return "deterministic"
        return (cts + timedelta(hours=max_age_hours)).isoformat()

    @staticmethod
    def _recommendation_id(
        *,
        ticker: str,
        recommendation_type: str,
        current_weight: float,
        proposed_weight: float,
        expected_return: float,
        confidence_adjusted_return: float,
        created_timestamp: str,
        policy_version: str,
    ) -> str:
        payload = (
            f"{ticker}|{recommendation_type}|{current_weight:.12f}|{proposed_weight:.12f}|"
            f"{expected_return:.12f}|{confidence_adjusted_return:.12f}|{created_timestamp}|{policy_version}"
        )
        return "PR-" + sha256(payload.encode("utf-8")).hexdigest()[:16].upper()

    @staticmethod
    def _hash_payload(payload: Any) -> str:
        return sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()
