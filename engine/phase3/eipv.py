from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .approval import ApprovalLogEntry, ApprovalState
from .context import ResearchContext
from .errors import Phase3ApprovalError, Phase3EIPVError


@dataclass(frozen=True)
class ScenarioValue:
    name: str
    probability: float
    return_delta: float
    intrinsic_value: float


@dataclass(frozen=True)
class EIPVResult:
    ticker: str
    bear_intrinsic_value: float
    base_intrinsic_value: float
    bull_intrinsic_value: float
    probability_weighted_intrinsic_value: float
    expected_annual_return: float
    margin_of_safety: float
    confidence: float
    explanation: str
    audit_trail: tuple[ApprovalLogEntry, ...] = field(default_factory=tuple)


def _scenario_mapping(scenario_assumptions: Mapping[str, Mapping[str, Any]] | None) -> dict[str, dict[str, Any]]:
    default = {
        "bear": {"probability": 0.2, "return_delta": -0.12},
        "base": {"probability": 0.5, "return_delta": 0.0},
        "bull": {"probability": 0.3, "return_delta": 0.12},
    }
    if not scenario_assumptions:
        return default
    merged = {name: dict(values) for name, values in default.items()}
    for name, values in scenario_assumptions.items():
        if name in merged:
            merged[name].update(values)
    return merged


class EIPVEngine:
    def estimate(
        self,
        research_context: ResearchContext,
        *,
        market_price: float,
        user_assumptions: Mapping[str, Any] | None = None,
        scenario_assumptions: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> EIPVResult:
        if research_context.approval_status is not ApprovalState.APPROVED_FOR_EIPV:
            raise Phase3ApprovalError(f"ResearchContext {research_context.ticker} is not approved for EIPV.")
        if market_price <= 0:
            raise Phase3EIPVError("market_price must be positive.")

        assumptions = dict(user_assumptions or {})
        horizon_years = float(assumptions.get("horizon_years", 1.0))
        expected_return_bias = float(assumptions.get("expected_return_bias", 0.0))
        signal_sensitivity = float(assumptions.get("signal_sensitivity", 0.20))
        confidence_weight = float(assumptions.get("confidence_weight", 0.05))

        phase2_signal = float(research_context.overall_phase2_score) / 100.0
        base_return_rate = expected_return_bias + (phase2_signal * signal_sensitivity)

        scenarios = _scenario_mapping(scenario_assumptions)
        computed: dict[str, ScenarioValue] = {}
        for name in ("bear", "base", "bull"):
            scenario = scenarios[name]
            probability = float(scenario.get("probability", 0.0))
            return_delta = float(scenario.get("return_delta", 0.0))
            annual_return = base_return_rate + return_delta
            intrinsic_value = market_price * (1.0 + annual_return * horizon_years)
            computed[name] = ScenarioValue(
                name=name,
                probability=probability,
                return_delta=return_delta,
                intrinsic_value=intrinsic_value,
            )

        probability_sum = sum(value.probability for value in computed.values())
        if probability_sum <= 0:
            raise Phase3EIPVError("Scenario probabilities must sum to a positive value.")

        probability_weighted_intrinsic_value = sum(value.probability * value.intrinsic_value for value in computed.values()) / probability_sum
        expected_annual_return = sum(value.probability * (base_return_rate + value.return_delta) for value in computed.values()) / probability_sum
        margin_of_safety = (probability_weighted_intrinsic_value - market_price) / market_price
        confidence = max(0.0, min(100.0, (research_context.confidence * 0.9) + (probability_sum * 10.0) + confidence_weight * 10.0))

        audit_trail = (
            ApprovalLogEntry(
                ticker=research_context.ticker,
                from_state=research_context.approval_status,
                to_state=research_context.approval_status,
                actor="eipv-engine",
                reason="Received approved ResearchContext",
                timestamp="audit",
                metadata={"market_price": market_price},
            ),
            ApprovalLogEntry(
                ticker=research_context.ticker,
                from_state=research_context.approval_status,
                to_state=research_context.approval_status,
                actor="eipv-engine",
                reason="Computed scenario values",
                timestamp="audit",
                metadata={name: computed[name].intrinsic_value for name in computed},
            ),
        )
        explanation = (
            f"{research_context.ticker} EIPV from approved ResearchContext using a {horizon_years:.2f}-year horizon "
            f"and Phase 2 score {research_context.overall_phase2_score:.2f}."
        )

        return EIPVResult(
            ticker=research_context.ticker,
            bear_intrinsic_value=computed["bear"].intrinsic_value,
            base_intrinsic_value=computed["base"].intrinsic_value,
            bull_intrinsic_value=computed["bull"].intrinsic_value,
            probability_weighted_intrinsic_value=probability_weighted_intrinsic_value,
            expected_annual_return=expected_annual_return,
            margin_of_safety=margin_of_safety,
            confidence=confidence,
            explanation=explanation,
            audit_trail=audit_trail,
        )
