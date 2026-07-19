from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .allocation_engine import AllocationEngine
from .decision_record import DecisionRecord
from .models import DailyCIOBrief, PortfolioHolding, PortfolioConstraint, WatchlistItem
from .outcome_reconciliation import RealizedOutcome
from .portfolio_plan import (
    AllocationChange,
    PortfolioOSInputs,
    PortfolioPlan,
    RequiredAction,
    ReplacementCandidate,
    PortfolioTargetPosition,
    write_portfolio_plan,
)
from .replacement_engine import ReplacementEngine
from .risk_budget import build_risk_budget


def _normalize_symbol(value: str) -> str:
    return str(value or "").strip().upper()


class PortfolioOS:
    def __init__(
        self,
        allocation_engine: AllocationEngine | None = None,
        replacement_engine: ReplacementEngine | None = None,
    ) -> None:
        self.allocation_engine = allocation_engine or AllocationEngine()
        self.replacement_engine = replacement_engine or ReplacementEngine()

    def generate_plan(
        self,
        inputs: PortfolioOSInputs,
        *,
        report_path: Path | None = None,
    ) -> PortfolioPlan:
        allocation_result = self.allocation_engine.build_allocation(inputs)
        replacement_candidates = self.replacement_engine.build_candidates(
            brief=inputs.decision_brief,
            current_portfolio=inputs.current_portfolio,
            watchlist=inputs.watchlist,
            decision_records=inputs.decision_records,
            realized_outcomes=inputs.realized_outcomes,
            profile_map=allocation_result.profile_map,
        )

        risk_budget = build_risk_budget(
            current_portfolio=inputs.current_portfolio,
            target_portfolio=allocation_result.target_portfolio,
            cash_target=allocation_result.cash_target,
            margin_settings=inputs.margin_settings,
            max_position_size=inputs.max_position_size,
            max_cash_allocation=inputs.max_cash_allocation,
        )

        required_actions = self._build_required_actions(
            target_portfolio=allocation_result.target_portfolio,
            replacement_candidates=replacement_candidates,
            cash_target=allocation_result.cash_target,
            current_cash_weight=self._current_cash_weight(inputs),
        )

        expected_portfolio_alpha = self._expected_portfolio_alpha(allocation_result.target_portfolio, brief=inputs.decision_brief)
        expected_portfolio_risk = self._expected_portfolio_risk(allocation_result.target_portfolio, risk_budget=risk_budget)
        confidence = self._plan_confidence(
            brief=inputs.decision_brief,
            allocation_confidence=allocation_result.confidence,
            risk_budget=risk_budget,
            replacement_candidates=replacement_candidates,
        )

        target_portfolio = tuple(sorted(allocation_result.target_portfolio, key=lambda item: (-item.target_weight, item.symbol)))
        plan = PortfolioPlan(
            date=inputs.date,
            current_portfolio=inputs.current_portfolio,
            target_portfolio=target_portfolio,
            required_actions=required_actions,
            replacement_candidates=replacement_candidates,
            allocation_changes=allocation_result.allocation_changes,
            cash_target=allocation_result.cash_target,
            risk_budget=risk_budget,
            expected_portfolio_alpha=expected_portfolio_alpha,
            expected_portfolio_risk=expected_portfolio_risk,
            confidence=confidence,
            executive_summary=self._build_executive_summary(
                brief=inputs.decision_brief,
                allocation_result=allocation_result,
                replacement_candidates=replacement_candidates,
                risk_budget=risk_budget,
            ),
        )

        write_portfolio_plan(plan, report_path=report_path)
        return plan

    @staticmethod
    def _current_cash_weight(inputs: PortfolioOSInputs) -> float:
        total_value = sum(max(0.0, float(holding.market_value)) for holding in inputs.current_portfolio) + max(0.0, float(inputs.cash_balance))
        if total_value <= 0:
            return 0.0
        return max(0.0, float(inputs.cash_balance)) / total_value

    @staticmethod
    def _build_required_actions(
        *,
        target_portfolio: tuple[PortfolioTargetPosition, ...],
        replacement_candidates: tuple[ReplacementCandidate, ...],
        cash_target: float,
        current_cash_weight: float,
    ) -> tuple[RequiredAction, ...]:
        actions: list[RequiredAction] = []
        priority = 1

        for position in sorted(target_portfolio, key=lambda item: (-abs(item.target_weight - item.current_weight), item.symbol)):
            delta = position.target_weight - position.current_weight
            if abs(delta) < 0.005:
                continue
            if delta > 0:
                text = f"Increase {position.symbol} to {_format_percent(position.target_weight)}"
            elif position.target_weight <= 0:
                text = f"Reduce {position.symbol} to 0.0%"
            else:
                text = f"Reduce {position.symbol} to {_format_percent(position.target_weight)}"
            actions.append(RequiredAction(priority=priority, text=text, symbol=position.symbol, action_type=position.action))
            priority += 1

        for replacement in replacement_candidates:
            actions.append(
                RequiredAction(
                    priority=priority,
                    text=f"Replace {replacement.symbol_to_sell} with {replacement.symbol_to_buy}",
                    symbol=replacement.symbol_to_buy,
                    action_type="replace",
                )
            )
            priority += 1

        if current_cash_weight < cash_target - 0.002:
            actions.append(
                RequiredAction(
                    priority=priority,
                    text=f"Deploy { _format_percent(cash_target - current_cash_weight) } cash",
                    symbol="CASH",
                    action_type="cash",
                )
            )
            priority += 1
        elif current_cash_weight > cash_target + 0.002:
            actions.append(
                RequiredAction(
                    priority=priority,
                    text=f"Hold excess cash near {_format_percent(cash_target)}",
                    symbol="CASH",
                    action_type="cash",
                )
            )
            priority += 1

        if not actions:
            actions.append(RequiredAction(priority=1, text="Hold", symbol="", action_type="hold"))

        return tuple(actions)

    @staticmethod
    def _expected_portfolio_alpha(target_portfolio: tuple[PortfolioTargetPosition, ...], *, brief: DailyCIOBrief) -> float:
        weighted = sum(max(0.0, position.target_weight) * (position.expected_alpha + 0.1 * brief.confidence_score / 10.0) for position in target_portfolio)
        total = sum(max(0.0, position.target_weight) for position in target_portfolio)
        return round(weighted / total, 2) if total > 0 else 0.0

    @staticmethod
    def _expected_portfolio_risk(target_portfolio: tuple[PortfolioTargetPosition, ...], *, risk_budget) -> float:
        if not target_portfolio:
            return 0.0
        weighted = sum(max(0.0, position.target_weight) * position.expected_risk for position in target_portfolio)
        total = sum(max(0.0, position.target_weight) for position in target_portfolio)
        base = weighted / total if total > 0 else 0.0
        return round(max(base, float(risk_budget.expected_volatility)), 2)

    @staticmethod
    def _plan_confidence(
        *,
        brief: DailyCIOBrief,
        allocation_confidence: float,
        risk_budget,
        replacement_candidates: tuple[ReplacementCandidate, ...],
    ) -> float:
        replacement_bonus = min(15.0, len(replacement_candidates) * 4.0)
        risk_modifier = max(0.0, 20.0 - float(risk_budget.expected_volatility))
        return max(
            0.0,
            min(
                100.0,
                (float(brief.confidence_score) * 0.35)
                + (float(allocation_confidence) * 0.40)
                + risk_modifier
                + replacement_bonus,
            ),
        )

    @staticmethod
    def _build_executive_summary(
        *,
        brief: DailyCIOBrief,
        allocation_result,
        replacement_candidates: tuple[ReplacementCandidate, ...],
        risk_budget,
    ) -> str:
        replacement_text = "no replacements recommended" if not replacement_candidates else f"{len(replacement_candidates)} replacement candidates identified"
        return (
            f"Portfolio OS translated the CIO brief into a target portfolio with cash at {_format_percent(allocation_result.cash_target)}. "
            f"The plan keeps the layer advisory-only, with {replacement_text}, expected alpha {allocation_result.expected_portfolio_alpha:.2f}, "
            f"and risk budget volatility {risk_budget.expected_volatility:.2f}. CIO brief confidence was {brief.confidence_score:.1f}."
        )


def _format_percent(value: float) -> str:
    return f"{value:.1%}"