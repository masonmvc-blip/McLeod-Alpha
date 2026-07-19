from __future__ import annotations

from collections import defaultdict

from .models import DecisionEngineInputs, PortfolioHealthResult


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _mean(values: list[float], default: float = 50.0) -> float:
    if not values:
        return default
    return sum(values) / len(values)


def _weighted_mean(values: list[tuple[float, float]], default: float = 50.0) -> float:
    if not values:
        return default
    weight_sum = sum(weight for weight, _ in values)
    if weight_sum <= 0:
        return default
    return sum(weight * score for weight, score in values) / weight_sum


def _bucket_risk(score: float) -> str:
    if score >= 80:
        return "LOW"
    if score >= 65:
        return "MODERATE"
    if score >= 45:
        return "ELEVATED"
    return "HIGH"


def compute_portfolio_health(inputs: DecisionEngineInputs) -> PortfolioHealthResult:
    holdings = tuple(inputs.holdings)
    total_value = sum(max(0.0, float(holding.market_value)) for holding in holdings)
    portfolio_value = total_value + max(0.0, float(inputs.cash_balance))
    cash_weight = (float(inputs.cash_balance) / portfolio_value) if portfolio_value > 0 else 0.0
    holding_weights = [
        (max(0.0, float(holding.market_value)) / total_value, holding)
        for holding in holdings
        if total_value > 0 and float(holding.market_value) > 0
    ]

    thesis_values = [
        (weight, _clamp(float(holding.thesis_health_score)))
        for weight, holding in holding_weights
    ] or [(1.0, _clamp(float(score))) for score in inputs.thesis_health_scores.values()]
    valuation_values = [
        (weight, _clamp(float(holding.valuation_score)))
        for weight, holding in holding_weights
    ] or [(1.0, _clamp(float(score))) for score in inputs.valuation_scores.values()]
    conviction_values = [
        (weight, _clamp(float(holding.conviction_score)))
        for weight, holding in holding_weights
    ] or [(1.0, _clamp(float(score))) for score in inputs.conviction_scores.values()]
    risk_values = [
        (weight, _clamp(float(holding.risk_score)))
        for weight, holding in holding_weights
    ] or [(1.0, _clamp(float(score))) for score in inputs.risk_scores.values()]
    liquidity_values = [
        (weight, _clamp(float(holding.liquidity_score)))
        for weight, holding in holding_weights
    ] or [(1.0, 50.0)]

    sector_weights = defaultdict(float)
    max_weight = 0.0
    for weight, holding in holding_weights:
        sector_weights[holding.sector or "Unknown"] += weight
        max_weight = max(max_weight, weight)

    sector_count = len(sector_weights)
    if holding_weights:
        hhi = sum(weight ** 2 for weight, _ in holding_weights)
        diversification_score = _clamp(100.0 * (1.0 - hhi) + min(20.0, sector_count * 4.0))
        concentration_score = _clamp(100.0 - max_weight * 100.0)
    else:
        diversification_score = 60.0
        concentration_score = 80.0

    if cash_weight < inputs.constraints.min_cash_weight:
        cash_allocation_score = _clamp((cash_weight / max(1e-9, inputs.constraints.min_cash_weight)) * 100.0)
    elif cash_weight <= inputs.constraints.target_cash_weight:
        cash_allocation_score = 100.0
    else:
        cash_allocation_score = _clamp(100.0 - (cash_weight - inputs.constraints.target_cash_weight) * 220.0)

    portfolio_risk_score = _clamp(100.0 - _weighted_mean(risk_values, default=50.0))
    thesis_health_score = _weighted_mean(thesis_values, default=50.0)
    valuation_score = _weighted_mean(valuation_values, default=50.0)
    expected_alpha_score = _clamp((0.45 * _weighted_mean(conviction_values, default=50.0)) + (0.35 * valuation_score) + (0.20 * thesis_health_score))
    liquidity_score = _weighted_mean(liquidity_values, default=50.0)

    component_scores = {
        "thesis_health": round(thesis_health_score, 2),
        "valuation": round(valuation_score, 2),
        "diversification": round(diversification_score, 2),
        "concentration": round(concentration_score, 2),
        "cash_allocation": round(cash_allocation_score, 2),
        "expected_alpha": round(expected_alpha_score, 2),
        "portfolio_risk": round(portfolio_risk_score, 2),
        "liquidity": round(liquidity_score, 2),
    }

    weights = {
        "thesis_health": 0.18,
        "valuation": 0.14,
        "diversification": 0.14,
        "concentration": 0.12,
        "cash_allocation": 0.12,
        "expected_alpha": 0.16,
        "portfolio_risk": 0.10,
        "liquidity": 0.04,
    }
    overall = sum(component_scores[key] * weight for key, weight in weights.items())
    overall_score = round(_clamp(overall), 2)

    return PortfolioHealthResult(
        overall_score=overall_score,
        component_scores=tuple(sorted(component_scores.items())),
        overall_risk=_bucket_risk(overall_score),
        cash_weight=round(cash_weight * 100.0, 2),
        total_portfolio_value=round(portfolio_value, 2),
        concentration_weight=round(max_weight * 100.0, 2),
        diversification_weight=round(diversification_score, 2),
    )