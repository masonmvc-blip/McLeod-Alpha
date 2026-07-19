from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .decision_record import DecisionRecord
from .models import DailyCIOBrief, PortfolioConstraint, PortfolioHolding, WatchlistItem
from .outcome_reconciliation import RealizedOutcome


DEFAULT_REPORT_PATH = Path("artifacts") / "cio" / "portfolio_plan.md"


def _stable_json_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_stable_json_value(item) for item in value]
    if isinstance(value, list):
        return [_stable_json_value(item) for item in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__") and not isinstance(value, (str, bytes, Mapping)):
        return {key: _stable_json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _stable_json_value(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    return value


@dataclass(frozen=True)
class PortfolioOSInputs:
    date: str
    decision_brief: DailyCIOBrief
    decision_records: tuple[DecisionRecord, ...] = field(default_factory=tuple)
    realized_outcomes: tuple[RealizedOutcome, ...] = field(default_factory=tuple)
    current_portfolio: tuple[PortfolioHolding, ...] = field(default_factory=tuple)
    cash_balance: float = 0.0
    watchlist: tuple[WatchlistItem, ...] = field(default_factory=tuple)
    risk_limits: PortfolioConstraint = field(default_factory=PortfolioConstraint)
    max_position_size: float = 0.15
    min_position_size: float = 0.02
    max_cash_allocation: float = 0.25
    margin_settings: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PortfolioTargetPosition:
    symbol: str
    current_weight: float
    target_weight: float
    current_value: float
    target_value: float
    action: str
    score: float
    expected_alpha: float
    expected_risk: float
    reason: str
    supporting_evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AllocationChange:
    symbol: str
    current_weight: float
    target_weight: float
    delta_weight: float
    current_value: float
    target_value: float
    action: str
    reason: str


@dataclass(frozen=True)
class RequiredAction:
    priority: int
    text: str
    symbol: str = ""
    action_type: str = ""


@dataclass(frozen=True)
class ReplacementCandidate:
    symbol_to_sell: str
    symbol_to_buy: str
    expected_alpha_gain: float
    confidence: float
    supporting_evidence: tuple[str, ...] = field(default_factory=tuple)
    rationale: str = ""


@dataclass(frozen=True)
class PortfolioPlan:
    date: str
    current_portfolio: tuple[PortfolioHolding, ...]
    target_portfolio: tuple[PortfolioTargetPosition, ...]
    required_actions: tuple[RequiredAction, ...]
    replacement_candidates: tuple[ReplacementCandidate, ...]
    allocation_changes: tuple[AllocationChange, ...]
    cash_target: float
    risk_budget: Any
    expected_portfolio_alpha: float
    expected_portfolio_risk: float
    confidence: float
    executive_summary: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["current_portfolio"] = [_stable_json_value(item) for item in self.current_portfolio]
        payload["target_portfolio"] = [_stable_json_value(item) for item in self.target_portfolio]
        payload["required_actions"] = [_stable_json_value(item) for item in self.required_actions]
        payload["replacement_candidates"] = [_stable_json_value(item) for item in self.replacement_candidates]
        payload["allocation_changes"] = [_stable_json_value(item) for item in self.allocation_changes]
        payload["risk_budget"] = _stable_json_value(self.risk_budget)
        return payload


def _format_weight(value: float) -> str:
    return f"{value:.1%}"


def render_portfolio_plan(plan: PortfolioPlan) -> str:
    lines = [
        f"# Portfolio Plan - {plan.date}",
        "",
        "## Executive Summary",
        plan.executive_summary,
        "",
        "## Target Portfolio",
        "| Symbol | Current Weight | Target Weight | Delta | Action | Expected Alpha | Expected Risk |",
        "| --- | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for position in sorted(plan.target_portfolio, key=lambda item: (-item.target_weight, item.symbol)):
        lines.append(
            f"| {position.symbol} | {_format_weight(position.current_weight)} | {_format_weight(position.target_weight)} | {_format_weight(position.target_weight - position.current_weight)} | {position.action} | {position.expected_alpha:.2f} | {position.expected_risk:.2f} |"
        )

    lines.extend([
        "",
        "## Allocation Changes",
        "| Symbol | Current Weight | Target Weight | Delta | Action |",
        "| --- | ---: | ---: | ---: | --- |",
    ])
    for change in sorted(plan.allocation_changes, key=lambda item: (-abs(item.delta_weight), item.symbol)):
        lines.append(
            f"| {change.symbol} | {_format_weight(change.current_weight)} | {_format_weight(change.target_weight)} | {_format_weight(change.delta_weight)} | {change.action} |"
        )

    lines.extend([
        "",
        "## Replacement Candidates",
    ])
    if plan.replacement_candidates:
        lines.append("| Sell | Buy | Expected Alpha Gain | Confidence | Evidence |")
        lines.append("| --- | --- | ---: | ---: | --- |")
        for candidate in plan.replacement_candidates:
            evidence = "; ".join(candidate.supporting_evidence) if candidate.supporting_evidence else "None"
            lines.append(
                f"| {candidate.symbol_to_sell} | {candidate.symbol_to_buy} | {candidate.expected_alpha_gain:.2f} | {candidate.confidence:.1f}% | {evidence} |"
            )
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Required Actions",
    ])
    for action in sorted(plan.required_actions, key=lambda item: item.priority):
        lines.append(f"- {action.text}")

    lines.extend([
        "",
        "## Risk Budget",
        f"- Portfolio concentration: {plan.risk_budget.concentration:.1%}",
        f"- Cash exposure: {plan.risk_budget.cash_exposure:.1%}",
        f"- Expected volatility: {plan.risk_budget.expected_volatility:.2f}",
        "- Sector exposure:",
    ])
    for sector, exposure in plan.risk_budget.sector_exposure:
        lines.append(f"  - {sector}: {_format_weight(exposure)}")

    lines.extend([
        "- Largest risks:",
    ])
    for risk in plan.risk_budget.largest_risks:
        lines.append(f"  - {risk}")

    lines.extend([
        "- Largest opportunities:",
    ])
    for opportunity in plan.risk_budget.largest_opportunities:
        lines.append(f"  - {opportunity}")

    lines.extend([
        "",
        "## Cash Recommendation",
        f"Target cash allocation: {_format_weight(plan.cash_target)}",
        "",
        "## Expected Improvement",
        f"Expected portfolio alpha: {plan.expected_portfolio_alpha:.2f}",
        f"Expected portfolio risk: {plan.expected_portfolio_risk:.2f}",
        f"Confidence: {plan.confidence:.1f}%",
    ])
    return "\n".join(lines) + "\n"


def write_portfolio_plan(plan: PortfolioPlan, report_path: Path | None = None) -> Path:
    output_path = Path(report_path or DEFAULT_REPORT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_portfolio_plan(plan), encoding="utf-8")
    return output_path