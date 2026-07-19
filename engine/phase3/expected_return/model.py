from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Any, Mapping, Sequence

from engine.phase3.context import ResearchContext

from .scenario import Scenario


class ExpectedReturnValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CalculationAuditEntry:
    step: str
    value: Any


@dataclass(frozen=True)
class ExpectedReturnResult:
    ticker: str
    bear_annualized_return: float
    base_annualized_return: float
    bull_annualized_return: float
    expected_annual_return: float
    expected_intrinsic_value: float
    margin_of_safety: float
    expected_volatility_estimate: float
    confidence_adjusted_expected_return: float
    calculation_audit: tuple[CalculationAuditEntry, ...] = field(default_factory=tuple)


class ExpectedReturnModel:
    PROBABILITY_TOLERANCE = 1e-9

    def evaluate(
        self,
        research_context: ResearchContext,
        *,
        market_price: float,
        bear_scenario: Scenario,
        base_scenario: Scenario,
        bull_scenario: Scenario,
        investment_horizon_years: float,
        user_assumptions: Mapping[str, Any],
    ) -> ExpectedReturnResult:
        self._validate_required_inputs(
            research_context=research_context,
            market_price=market_price,
            bear_scenario=bear_scenario,
            base_scenario=base_scenario,
            bull_scenario=bull_scenario,
            investment_horizon_years=investment_horizon_years,
            user_assumptions=user_assumptions,
        )

        scenarios = {
            "bear": bear_scenario,
            "base": base_scenario,
            "bull": bull_scenario,
        }
        self._validate_probabilities(list(scenarios.values()))

        horizon = float(investment_horizon_years)
        annualized_returns = {
            name: self._annualized_return(
                market_price=market_price,
                intrinsic_value=float(scenario.intrinsic_value),
                horizon_years=horizon,
            )
            for name, scenario in scenarios.items()
        }
        expected_intrinsic_value = sum(s.intrinsic_value * s.probability for s in scenarios.values())
        expected_annual_return = sum(annualized_returns[name] * scenario.probability for name, scenario in scenarios.items())
        margin_of_safety = (expected_intrinsic_value - market_price) / market_price
        expected_volatility_estimate = self._probability_weighted_stddev(
            values=list(annualized_returns.values()),
            probabilities=[scenarios[name].probability for name in ("bear", "base", "bull")],
            mean=expected_annual_return,
        )

        confidence_weight = float(user_assumptions["confidence_weight"])
        uncertainty_penalty = float(user_assumptions["uncertainty_penalty"])
        confidence_factor = max(0.0, min(1.0, float(research_context.confidence) / 100.0))
        confidence_adjusted_expected_return = (
            expected_annual_return * (1.0 + confidence_weight * confidence_factor)
        ) - (uncertainty_penalty * expected_volatility_estimate)

        audit = (
            CalculationAuditEntry("ticker", research_context.ticker),
            CalculationAuditEntry("market_price", float(market_price)),
            CalculationAuditEntry("investment_horizon_years", horizon),
            CalculationAuditEntry("bear_probability", float(bear_scenario.probability)),
            CalculationAuditEntry("base_probability", float(base_scenario.probability)),
            CalculationAuditEntry("bull_probability", float(bull_scenario.probability)),
            CalculationAuditEntry("bear_annualized_return", annualized_returns["bear"]),
            CalculationAuditEntry("base_annualized_return", annualized_returns["base"]),
            CalculationAuditEntry("bull_annualized_return", annualized_returns["bull"]),
            CalculationAuditEntry("expected_intrinsic_value", expected_intrinsic_value),
            CalculationAuditEntry("expected_annual_return", expected_annual_return),
            CalculationAuditEntry("expected_volatility_estimate", expected_volatility_estimate),
            CalculationAuditEntry("confidence_adjusted_expected_return", confidence_adjusted_expected_return),
        )

        return ExpectedReturnResult(
            ticker=research_context.ticker,
            bear_annualized_return=annualized_returns["bear"],
            base_annualized_return=annualized_returns["base"],
            bull_annualized_return=annualized_returns["bull"],
            expected_annual_return=expected_annual_return,
            expected_intrinsic_value=expected_intrinsic_value,
            margin_of_safety=margin_of_safety,
            expected_volatility_estimate=expected_volatility_estimate,
            confidence_adjusted_expected_return=confidence_adjusted_expected_return,
            calculation_audit=audit,
        )

    @staticmethod
    def _annualized_return(*, market_price: float, intrinsic_value: float, horizon_years: float) -> float:
        gross = intrinsic_value / market_price
        return pow(gross, 1.0 / horizon_years) - 1.0

    @staticmethod
    def _probability_weighted_stddev(*, values: Sequence[float], probabilities: Sequence[float], mean: float) -> float:
        variance = sum(prob * ((value - mean) ** 2) for value, prob in zip(values, probabilities, strict=True))
        return sqrt(max(0.0, variance))

    def _validate_probabilities(self, scenarios: Sequence[Scenario]) -> None:
        probs = [float(s.probability) for s in scenarios]
        if any(prob < 0.0 for prob in probs):
            raise ExpectedReturnValidationError("Scenario probabilities must be non-negative.")
        if abs(sum(probs) - 1.0) > self.PROBABILITY_TOLERANCE:
            raise ExpectedReturnValidationError("Scenario probabilities must sum to 1.0 within tolerance.")

    @staticmethod
    def _validate_required_inputs(
        *,
        research_context: ResearchContext,
        market_price: float,
        bear_scenario: Scenario,
        base_scenario: Scenario,
        bull_scenario: Scenario,
        investment_horizon_years: float,
        user_assumptions: Mapping[str, Any],
    ) -> None:
        if not isinstance(research_context, ResearchContext):
            raise ExpectedReturnValidationError("ExpectedReturnModel requires a ResearchContext input.")
        if market_price <= 0:
            raise ExpectedReturnValidationError("market_price must be positive.")
        if investment_horizon_years <= 0:
            raise ExpectedReturnValidationError("investment_horizon_years must be positive.")
        if not user_assumptions:
            raise ExpectedReturnValidationError("user_assumptions are required.")

        required_assumptions = ("confidence_weight", "uncertainty_penalty")
        missing = [key for key in required_assumptions if key not in user_assumptions]
        if missing:
            raise ExpectedReturnValidationError(f"Missing required assumptions: {', '.join(missing)}")

        for scenario, name in ((bear_scenario, "bear"), (base_scenario, "base"), (bull_scenario, "bull")):
            if scenario.intrinsic_value <= 0:
                raise ExpectedReturnValidationError(f"{name} scenario intrinsic_value must be positive.")
            if not str(scenario.rationale).strip():
                raise ExpectedReturnValidationError(f"{name} scenario rationale is required.")
