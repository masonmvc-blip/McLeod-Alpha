from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from math import sqrt
from statistics import mean
from typing import Any, Sequence

from engine.phase3.decision_engine.model import DecisionResult
from engine.phase3.expected_return.model import ExpectedReturnResult

from .types import CalibrationAudit, CalibrationAuditStep, OutcomeRecord


class CalibrationValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CalibrationResult:
    ticker: str
    measurable: bool
    measurement_state: str
    forecast_error: float | None
    calibration_error: float | None
    confidence_calibration: float | None
    brier_score: float | None
    bias_estimate: float | None
    rolling_statistics: dict[str, float]
    calibration_audit: CalibrationAudit


class CalibrationModel:
    def evaluate(
        self,
        expected_return_result: ExpectedReturnResult,
        decision_result: DecisionResult,
        *,
        outcome_record: OutcomeRecord | None = None,
        outcome_history: Sequence[OutcomeRecord] | None = None,
    ) -> CalibrationResult:
        self._validate_inputs(expected_return_result, decision_result, outcome_record, outcome_history or ())

        timestamp = self._deterministic_timestamp(outcome_record)
        steps: list[CalibrationAuditStep] = []
        missing_reasons: list[str] = []

        if outcome_record is None:
            missing_reasons.append("OutcomeRecord is not available yet.")
        elif outcome_record.realized_return is None:
            missing_reasons.append("realized_return is not available yet.")

        measurable = len(missing_reasons) == 0
        if not measurable:
            steps.append(
                CalibrationAuditStep(
                    step="missing_outcome_detection",
                    passed=False,
                    detail="Calibration metrics are not yet measurable.",
                    timestamp=timestamp,
                    record={"missing_reasons": tuple(missing_reasons)},
                )
            )
            audit = CalibrationAudit(
                ticker=expected_return_result.ticker,
                measurable=False,
                missing_outcome_reasons=tuple(missing_reasons),
                steps=tuple(steps),
                deterministic_record=self._deterministic_record(
                    expected_return_result,
                    decision_result,
                    outcome_record,
                    measurable=False,
                    extra={"missing_reasons": tuple(missing_reasons)},
                ),
            )
            return CalibrationResult(
                ticker=expected_return_result.ticker,
                measurable=False,
                measurement_state="Not Yet Measurable",
                forecast_error=None,
                calibration_error=None,
                confidence_calibration=None,
                brier_score=None,
                bias_estimate=None,
                rolling_statistics={"history_count": float(len(outcome_history or ()))},
                calibration_audit=audit,
            )

        assert outcome_record is not None
        realized_return = float(outcome_record.realized_return)
        forecast_error = realized_return - float(expected_return_result.expected_annual_return)
        calibration_error = abs(forecast_error)
        confidence_target = 1.0 if realized_return >= 0.0 else 0.0
        confidence_prediction = max(0.0, min(1.0, float(decision_result.research_confidence) / 100.0))
        confidence_calibration = confidence_target - confidence_prediction
        brier_score = (confidence_prediction - confidence_target) ** 2
        bias_estimate = self._bias_estimate(outcome_history or (), forecast_error)
        rolling = self._rolling_statistics(outcome_history or (), forecast_error)

        steps.append(
            CalibrationAuditStep(
                step="validation",
                passed=True,
                detail="All calibration inputs are valid.",
                timestamp=timestamp,
                record={"history_count": len(outcome_history or ())},
            )
        )
        steps.append(
            CalibrationAuditStep(
                step="metric_calculation",
                passed=True,
                detail="Computed forecast and calibration metrics.",
                timestamp=timestamp,
                record={
                    "forecast_error": forecast_error,
                    "calibration_error": calibration_error,
                    "confidence_calibration": confidence_calibration,
                    "brier_score": brier_score,
                    "bias_estimate": bias_estimate,
                },
            )
        )

        audit = CalibrationAudit(
            ticker=expected_return_result.ticker,
            measurable=True,
            missing_outcome_reasons=(),
            steps=tuple(steps),
            deterministic_record=self._deterministic_record(
                expected_return_result,
                decision_result,
                outcome_record,
                measurable=True,
                extra={
                    "forecast_error": forecast_error,
                    "calibration_error": calibration_error,
                    "confidence_calibration": confidence_calibration,
                    "brier_score": brier_score,
                    "bias_estimate": bias_estimate,
                },
            ),
        )
        return CalibrationResult(
            ticker=expected_return_result.ticker,
            measurable=True,
            measurement_state="Measurable",
            forecast_error=forecast_error,
            calibration_error=calibration_error,
            confidence_calibration=confidence_calibration,
            brier_score=brier_score,
            bias_estimate=bias_estimate,
            rolling_statistics=rolling,
            calibration_audit=audit,
        )

    @staticmethod
    def _validate_inputs(
        expected_return_result: ExpectedReturnResult,
        decision_result: DecisionResult,
        outcome_record: OutcomeRecord | None,
        outcome_history: Sequence[OutcomeRecord],
    ) -> None:
        if not isinstance(expected_return_result, ExpectedReturnResult):
            raise CalibrationValidationError("CalibrationModel requires ExpectedReturnResult.")
        if not isinstance(decision_result, DecisionResult):
            raise CalibrationValidationError("CalibrationModel requires DecisionResult.")
        if expected_return_result.ticker != decision_result.ticker:
            raise CalibrationValidationError("Ticker mismatch between ExpectedReturnResult and DecisionResult.")
        if outcome_record is not None and not isinstance(outcome_record, OutcomeRecord):
            raise CalibrationValidationError("outcome_record must be an OutcomeRecord when provided.")
        if outcome_record is not None and outcome_record.ticker != expected_return_result.ticker:
            raise CalibrationValidationError("OutcomeRecord ticker mismatch.")
        for item in outcome_history:
            if not isinstance(item, OutcomeRecord):
                raise CalibrationValidationError("outcome_history items must be OutcomeRecord instances.")
            if item.ticker != expected_return_result.ticker:
                raise CalibrationValidationError("Outcome history ticker mismatch.")

    @staticmethod
    def _deterministic_timestamp(outcome_record: OutcomeRecord | None) -> str:
        if outcome_record and outcome_record.evaluation_date:
            return outcome_record.evaluation_date
        return "deterministic"

    @staticmethod
    def _extract_errors(outcome_history: Sequence[OutcomeRecord]) -> list[float]:
        errors: list[float] = []
        for item in outcome_history:
            if item.realized_return is None:
                continue
            errors.append(float(item.realized_return) - float(item.expected_return))
        return errors

    def _bias_estimate(self, outcome_history: Sequence[OutcomeRecord], current_error: float) -> float:
        errors = self._extract_errors(outcome_history)
        errors.append(current_error)
        return mean(errors)

    def _rolling_statistics(self, outcome_history: Sequence[OutcomeRecord], current_error: float) -> dict[str, float]:
        errors = self._extract_errors(outcome_history)
        errors.append(current_error)
        variance = mean([(value - mean(errors)) ** 2 for value in errors]) if errors else 0.0
        return {
            "history_count": float(len(errors)),
            "rolling_mean_error": mean(errors) if errors else 0.0,
            "rolling_rmse": sqrt(max(0.0, variance)),
        }

    @staticmethod
    def _deterministic_record(
        expected_return_result: ExpectedReturnResult,
        decision_result: DecisionResult,
        outcome_record: OutcomeRecord | None,
        *,
        measurable: bool,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        outcome_key = "none"
        if outcome_record is not None:
            outcome_key = (
                f"{outcome_record.forecast_date}|{outcome_record.evaluation_date}|{outcome_record.expected_return:.12f}|"
                f"{outcome_record.realized_return}|{outcome_record.expected_intrinsic_value:.12f}|{outcome_record.realized_value}"
            )
        payload = (
            f"{expected_return_result.ticker}|{expected_return_result.expected_annual_return:.12f}|"
            f"{expected_return_result.confidence_adjusted_expected_return:.12f}|{decision_result.decision_eligible}|"
            f"{decision_result.approval_status.value}|{measurable}|{outcome_key}|{sorted(extra.items())}"
        )
        return {
            "ticker": expected_return_result.ticker,
            "measurable": measurable,
            "record_hash": sha256(payload.encode("utf-8")).hexdigest(),
            "extra": dict(extra),
        }
