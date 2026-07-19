from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .models import PortfolioHolding
from .portfolio_plan import PortfolioTargetPosition


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class RiskBudget:
    concentration: float
    sector_exposure: tuple[tuple[str, float], ...]
    cash_exposure: float
    expected_volatility: float
    largest_risks: tuple[str, ...] = field(default_factory=tuple)
    largest_opportunities: tuple[str, ...] = field(default_factory=tuple)


def build_risk_budget(
    *,
    current_portfolio: tuple[PortfolioHolding, ...],
    target_portfolio: tuple[PortfolioTargetPosition, ...],
    cash_target: float,
    margin_settings: Mapping[str, object],
    max_position_size: float,
    max_cash_allocation: float,
) -> RiskBudget:
    target_weights = {position.symbol: max(0.0, float(position.target_weight)) for position in target_portfolio}
    current_weights = {holding.symbol.upper(): max(0.0, float(holding.market_value)) for holding in current_portfolio}
    total_target_weight = sum(target_weights.values()) + max(0.0, float(cash_target))
    normalized_total = total_target_weight if total_target_weight > 0 else 1.0

    sector_exposure_map: dict[str, float] = {}
    for holding in current_portfolio:
        weight = target_weights.get(holding.symbol.upper(), 0.0)
        if weight <= 0:
            continue
        sector = holding.sector or "Unknown"
        sector_exposure_map[sector] = sector_exposure_map.get(sector, 0.0) + weight

    concentration = max((weight for weight in target_weights.values()), default=0.0)
    sector_exposure = tuple(sorted((sector, exposure / normalized_total) for sector, exposure in sector_exposure_map.items()))
    cash_exposure = _clamp(float(cash_target), 0.0, float(max_cash_allocation))

    holding_risk = 0.0
    for position in target_portfolio:
        risk_component = max(0.0, min(100.0, float(position.expected_risk))) / 100.0
        holding_risk += max(0.0, float(position.target_weight)) * risk_component

    concentration_penalty = min(0.25, concentration * 0.6)
    margin_pressure = 0.0
    if margin_settings:
        maintenance = float(margin_settings.get("maintenance_requirement", 0.0) or 0.0)
        buying_power = float(margin_settings.get("buying_power", 0.0) or 0.0)
        if buying_power > 0:
            margin_pressure = _clamp(maintenance / buying_power, 0.0, 1.0)

    expected_volatility = round((holding_risk + concentration_penalty + (cash_exposure * 0.25) + margin_pressure * 0.15) * 100.0, 2)

    largest_risks = []
    for sector, exposure in sorted(sector_exposure_map.items(), key=lambda item: (-item[1], item[0]))[:3]:
        largest_risks.append(f"{sector} concentration at {exposure / normalized_total:.1%}")
    if concentration > max_position_size:
        largest_risks.append(f"Single-name concentration above cap at {concentration:.1%}")
    if margin_pressure > 0:
        largest_risks.append(f"Margin pressure score {margin_pressure:.2f}")

    largest_opportunities = []
    for position in sorted(target_portfolio, key=lambda item: (-item.expected_alpha, item.symbol))[:3]:
        if position.expected_alpha > 0:
            largest_opportunities.append(f"{position.symbol} alpha potential {position.expected_alpha:.2f}")
    if cash_exposure > 0:
        largest_opportunities.append(f"Deploy {cash_exposure:.1%} cash if higher-conviction names appear")

    return RiskBudget(
        concentration=round(concentration, 4),
        sector_exposure=sector_exposure,
        cash_exposure=round(cash_exposure, 4),
        expected_volatility=expected_volatility,
        largest_risks=tuple(largest_risks or ("No major concentration issues detected",)),
        largest_opportunities=tuple(largest_opportunities or ("Maintain optionality for higher-conviction opportunities",)),
    )