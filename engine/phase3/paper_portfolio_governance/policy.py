from __future__ import annotations

from dataclasses import dataclass


class PaperPolicyValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PaperRecommendationPolicy:
    version: str
    allowed_recommendation_types: tuple[str, ...]
    minimum_decision_eligibility: bool
    minimum_expected_return: float
    minimum_confidence: float
    maximum_position_weight: float
    maximum_sector_weight: float
    maximum_portfolio_turnover: float
    minimum_cash_reserve: float
    maximum_number_of_holdings: int
    prohibited_tickers: tuple[str, ...]
    required_approvals: tuple[str, ...]
    maximum_recommendation_age_hours: int
    calibration_requirements: tuple[str, ...]
    simulation_requirements: tuple[str, ...]
    shadow_allocation_requirements: tuple[str, ...]

    def validate(self) -> None:
        if not self.version.strip():
            raise PaperPolicyValidationError("Policy version is required.")
        if not self.allowed_recommendation_types:
            raise PaperPolicyValidationError("At least one recommendation type is required.")
        if self.minimum_expected_return < -1.0 or self.minimum_expected_return > 10.0:
            raise PaperPolicyValidationError("minimum_expected_return is out of supported range.")
        if self.minimum_confidence < 0.0 or self.minimum_confidence > 100.0:
            raise PaperPolicyValidationError("minimum_confidence must be in [0, 100].")
        if self.maximum_position_weight <= 0.0 or self.maximum_position_weight > 1.0:
            raise PaperPolicyValidationError("maximum_position_weight must be in (0, 1].")
        if self.maximum_sector_weight <= 0.0 or self.maximum_sector_weight > 1.0:
            raise PaperPolicyValidationError("maximum_sector_weight must be in (0, 1].")
        if self.maximum_portfolio_turnover < 0.0 or self.maximum_portfolio_turnover > 1.0:
            raise PaperPolicyValidationError("maximum_portfolio_turnover must be in [0, 1].")
        if self.minimum_cash_reserve < 0.0 or self.minimum_cash_reserve >= 1.0:
            raise PaperPolicyValidationError("minimum_cash_reserve must be in [0, 1).")
        if self.maximum_number_of_holdings <= 0:
            raise PaperPolicyValidationError("maximum_number_of_holdings must be positive.")
        if self.maximum_recommendation_age_hours <= 0:
            raise PaperPolicyValidationError("maximum_recommendation_age_hours must be positive.")
        if not self.required_approvals:
            raise PaperPolicyValidationError("required_approvals cannot be empty.")
        if not self.calibration_requirements:
            raise PaperPolicyValidationError("calibration_requirements cannot be empty.")
        if not self.simulation_requirements:
            raise PaperPolicyValidationError("simulation_requirements cannot be empty.")
        if not self.shadow_allocation_requirements:
            raise PaperPolicyValidationError("shadow_allocation_requirements cannot be empty.")

    @classmethod
    def default(cls) -> "PaperRecommendationPolicy":
        return cls(
            version="paper-governance-v1",
            allowed_recommendation_types=(
                "INITIATE_POSITION",
                "INCREASE_WEIGHT",
                "DECREASE_WEIGHT",
                "EXIT_POSITION",
                "REBALANCE",
                "HOLD",
            ),
            minimum_decision_eligibility=True,
            minimum_expected_return=0.0,
            minimum_confidence=50.0,
            maximum_position_weight=0.40,
            maximum_sector_weight=0.60,
            maximum_portfolio_turnover=0.80,
            minimum_cash_reserve=0.10,
            maximum_number_of_holdings=10,
            prohibited_tickers=(),
            required_approvals=("risk", "cio"),
            maximum_recommendation_age_hours=72,
            calibration_requirements=("MEASURABLE_OR_NOT_YET_MEASURABLE",),
            simulation_requirements=("POSITIVE_CAGR", "NON_NEGATIVE_CASH_UTILIZATION"),
            shadow_allocation_requirements=("WEIGHTS_RECONCILE", "NO_CONSTRAINT_VIOLATIONS"),
        )
