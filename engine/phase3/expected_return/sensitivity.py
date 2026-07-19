from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from engine.phase3.context import ResearchContext

from .model import ExpectedReturnModel, ExpectedReturnResult
from .scenario import Scenario


@dataclass(frozen=True)
class SensitivityResult:
    base_expected_annual_return: float
    base_expected_intrinsic_value: float
    delta_expected_return: float
    delta_intrinsic_value: float
    confidence_impact: float
    baseline: ExpectedReturnResult
    stressed: ExpectedReturnResult
    audit: tuple[tuple[str, Any], ...] = field(default_factory=tuple)


class SensitivityAnalyzer:
    def __init__(self, model: ExpectedReturnModel | None = None):
        self.model = model or ExpectedReturnModel()

    def analyze(
        self,
        *,
        research_context: ResearchContext,
        market_price: float,
        bear_scenario: Scenario,
        base_scenario: Scenario,
        bull_scenario: Scenario,
        investment_horizon_years: float,
        user_assumptions: Mapping[str, Any],
        stressed_bear_probability: float,
        stressed_base_probability: float,
        stressed_bull_probability: float,
        stressed_bear_intrinsic_value: float,
        stressed_base_intrinsic_value: float,
        stressed_bull_intrinsic_value: float,
        stressed_horizon_years: float,
    ) -> SensitivityResult:
        baseline = self.model.evaluate(
            research_context,
            market_price=market_price,
            bear_scenario=bear_scenario,
            base_scenario=base_scenario,
            bull_scenario=bull_scenario,
            investment_horizon_years=investment_horizon_years,
            user_assumptions=user_assumptions,
        )

        stressed = self.model.evaluate(
            research_context,
            market_price=market_price,
            bear_scenario=Scenario(
                intrinsic_value=stressed_bear_intrinsic_value,
                probability=stressed_bear_probability,
                rationale=bear_scenario.rationale,
                supporting_assumptions=bear_scenario.supporting_assumptions,
            ),
            base_scenario=Scenario(
                intrinsic_value=stressed_base_intrinsic_value,
                probability=stressed_base_probability,
                rationale=base_scenario.rationale,
                supporting_assumptions=base_scenario.supporting_assumptions,
            ),
            bull_scenario=Scenario(
                intrinsic_value=stressed_bull_intrinsic_value,
                probability=stressed_bull_probability,
                rationale=bull_scenario.rationale,
                supporting_assumptions=bull_scenario.supporting_assumptions,
            ),
            investment_horizon_years=stressed_horizon_years,
            user_assumptions=user_assumptions,
        )

        delta_expected_return = stressed.expected_annual_return - baseline.expected_annual_return
        delta_intrinsic_value = stressed.expected_intrinsic_value - baseline.expected_intrinsic_value
        confidence_impact = stressed.confidence_adjusted_expected_return - baseline.confidence_adjusted_expected_return

        return SensitivityResult(
            base_expected_annual_return=baseline.expected_annual_return,
            base_expected_intrinsic_value=baseline.expected_intrinsic_value,
            delta_expected_return=delta_expected_return,
            delta_intrinsic_value=delta_intrinsic_value,
            confidence_impact=confidence_impact,
            baseline=baseline,
            stressed=stressed,
            audit=(
                ("delta_expected_return", delta_expected_return),
                ("delta_intrinsic_value", delta_intrinsic_value),
                ("confidence_impact", confidence_impact),
            ),
        )
