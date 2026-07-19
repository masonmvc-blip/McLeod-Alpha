from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping, Sequence

from engine.phase3.decision_engine.model import DecisionResult
from engine.phase3.expected_return.model import ExpectedReturnResult

from .types import PortfolioConstraints, ReplacementEvaluation, ShadowAllocationAudit, ShadowAllocationAuditStep


class ShadowAllocationValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ShadowAllocationResult:
    proposed_target_weights: Mapping[str, float]
    proposed_dollar_allocations: Mapping[str, float]
    proposed_cash_weight: float
    concentration_metrics: Mapping[str, float]
    constraint_violations: tuple[str, ...]
    replacement_candidates: tuple[ReplacementEvaluation, ...]
    expected_portfolio_return: float
    confidence_adjusted_portfolio_return: float
    audit: ShadowAllocationAudit


class ShadowAllocationModel:
    METHODS = (
        "equal_weight",
        "expected_return_weight",
        "confidence_adjusted_return_weight",
        "score_weight",
        "user_defined_weight",
    )

    def evaluate(
        self,
        *,
        decision_results: Sequence[DecisionResult],
        expected_return_results: Mapping[str, ExpectedReturnResult],
        current_shadow_holdings: Mapping[str, float],
        available_shadow_cash: float,
        constraints: PortfolioConstraints,
        approved_allocation_method: str,
        user_defined_weights: Mapping[str, float] | None = None,
        sector_map: Mapping[str, str] | None = None,
        production_portfolio_access_attempted: bool = False,
        frozen_artifacts_valid: bool = True,
        timestamp: str = "deterministic",
    ) -> ShadowAllocationResult:
        steps: list[ShadowAllocationAuditStep] = []
        violations: list[str] = []

        self._validate_inputs(
            decision_results=decision_results,
            expected_return_results=expected_return_results,
            current_shadow_holdings=current_shadow_holdings,
            available_shadow_cash=available_shadow_cash,
            constraints=constraints,
            approved_allocation_method=approved_allocation_method,
            production_portfolio_access_attempted=production_portfolio_access_attempted,
            frozen_artifacts_valid=frozen_artifacts_valid,
        )
        steps.append(
            ShadowAllocationAuditStep(
                step="input_validation",
                passed=True,
                detail="Input contracts are valid.",
                timestamp=timestamp,
            )
        )

        decision_map = {row.ticker: row for row in decision_results}
        prohibited = {ticker.upper() for ticker in constraints.prohibited_tickers}
        required = {ticker.upper() for ticker in constraints.required_tickers}
        sector_map = {k.upper(): v for k, v in (sector_map or {}).items()}

        eligible_tickers = [
            ticker
            for ticker, decision in sorted(decision_map.items())
            if decision.decision_eligible and ticker in expected_return_results and ticker.upper() not in prohibited
        ]
        if not eligible_tickers:
            raise ShadowAllocationValidationError("No eligible tickers available after filtering.")

        blocked = [ticker for ticker, decision in sorted(decision_map.items()) if not decision.decision_eligible]
        for ticker in blocked:
            violations.append(f"INELIGIBLE_{ticker}")

        raw_weights = self._build_raw_weights(
            method=approved_allocation_method,
            tickers=eligible_tickers,
            decisions=decision_map,
            expected=expected_return_results,
            user_weights={k.upper(): v for k, v in (user_defined_weights or {}).items()},
        )

        normalized = self._normalize(raw_weights)
        normalized = self._enforce_max_holdings(normalized, constraints.maximum_number_of_holdings)
        normalized = self._apply_position_limits(normalized, constraints, violations)
        normalized = self._apply_sector_limit(normalized, constraints.maximum_sector_weight, sector_map, violations)

        if any(ticker not in normalized for ticker in required):
            missing = sorted(ticker for ticker in required if ticker not in normalized)
            violations.append("MISSING_REQUIRED_" + ",".join(missing))

        portfolio_value = float(sum(current_shadow_holdings.values()) + available_shadow_cash)
        if portfolio_value <= 0:
            raise ShadowAllocationValidationError("Total shadow portfolio value must be positive.")

        max_invested_fraction = min(
            1.0 - constraints.minimum_cash_reserve,
            constraints.maximum_total_invested_capital / portfolio_value,
        )
        max_invested_fraction = max(0.0, max_invested_fraction)

        normalized = {ticker: weight * max_invested_fraction for ticker, weight in normalized.items()}
        sum_weights = sum(normalized.values())
        if abs(sum_weights - max_invested_fraction) > 1e-9 and sum_weights > 0:
            normalized = {ticker: weight * (max_invested_fraction / sum_weights) for ticker, weight in normalized.items()}

        turnover = self._turnover(current_shadow_holdings, normalized, portfolio_value)
        if turnover > constraints.maximum_turnover:
            violations.append("MAX_TURNOVER_EXCEEDED")
            shrink = constraints.maximum_turnover / turnover if turnover > 0 else 0.0
            normalized = self._shrink_to_current(current_shadow_holdings, normalized, portfolio_value, shrink)

        sum_weights = sum(normalized.values())
        if sum_weights > 1.000000001:
            raise ShadowAllocationValidationError("Weights exceed 100% after constraints.")
        cash_weight = max(0.0, 1.0 - sum_weights)
        if cash_weight + 1e-9 < constraints.minimum_cash_reserve:
            violations.append("MIN_CASH_RESERVE_BREACH")

        proposed_dollars = {ticker: weight * portfolio_value for ticker, weight in sorted(normalized.items())}
        concentration = self._concentration_metrics(normalized)
        expected_portfolio_return = sum(
            normalized[ticker] * expected_return_results[ticker].expected_annual_return for ticker in normalized
        )
        confidence_adjusted_portfolio_return = sum(
            normalized[ticker] * expected_return_results[ticker].confidence_adjusted_expected_return for ticker in normalized
        )

        replacements = self._replacement_candidates(
            current_shadow_holdings=current_shadow_holdings,
            proposed_weights=normalized,
            expected=expected_return_results,
            constraints=constraints,
            portfolio_value=portfolio_value,
        )

        deterministic_record = {
            "method": approved_allocation_method,
            "tickers": tuple(sorted(normalized.keys())),
            "weights": tuple((ticker, normalized[ticker]) for ticker in sorted(normalized.keys())),
            "cash_weight": cash_weight,
            "violations": tuple(sorted(violations)),
            "turnover": self._turnover(current_shadow_holdings, normalized, portfolio_value),
        }
        config_hash = self._configuration_hash(
            method=approved_allocation_method,
            constraints=constraints,
            deterministic_record=deterministic_record,
            user_weights=user_defined_weights or {},
            sector_map=sector_map,
        )

        steps.append(
            ShadowAllocationAuditStep(
                step="allocation",
                passed=True,
                detail="Calculated shadow-only allocations.",
                timestamp=timestamp,
                record={
                    "proposed_weight_count": len(normalized),
                    "cash_weight": cash_weight,
                    "violations": tuple(sorted(violations)),
                },
            )
        )

        rejected = tuple(sorted(set(blocked + [ticker for ticker in prohibited if ticker in decision_map])))
        audit = ShadowAllocationAudit(
            inputs={
                "available_shadow_cash": available_shadow_cash,
                "holding_count": len(current_shadow_holdings),
                "decision_count": len(decision_results),
                "expected_count": len(expected_return_results),
            },
            validation_steps=tuple(steps),
            allocation_method=approved_allocation_method,
            constraint_checks=tuple(sorted(set(violations))),
            rejected_candidates=rejected,
            configuration_hash=config_hash,
            deterministic_execution_record=deterministic_record,
            timestamp_metadata={"as_of": timestamp},
        )

        return ShadowAllocationResult(
            proposed_target_weights={ticker: normalized.get(ticker, 0.0) for ticker in sorted(normalized.keys())},
            proposed_dollar_allocations={ticker: proposed_dollars[ticker] for ticker in sorted(proposed_dollars.keys())},
            proposed_cash_weight=cash_weight,
            concentration_metrics=concentration,
            constraint_violations=tuple(sorted(set(violations))),
            replacement_candidates=replacements,
            expected_portfolio_return=expected_portfolio_return,
            confidence_adjusted_portfolio_return=confidence_adjusted_portfolio_return,
            audit=audit,
        )

    def _validate_inputs(
        self,
        *,
        decision_results: Sequence[DecisionResult],
        expected_return_results: Mapping[str, ExpectedReturnResult],
        current_shadow_holdings: Mapping[str, float],
        available_shadow_cash: float,
        constraints: PortfolioConstraints,
        approved_allocation_method: str,
        production_portfolio_access_attempted: bool,
        frozen_artifacts_valid: bool,
    ) -> None:
        if production_portfolio_access_attempted:
            raise ShadowAllocationValidationError("Production portfolio access attempted.")
        if not frozen_artifacts_valid:
            raise ShadowAllocationValidationError("Frozen artifact validation failed.")
        if approved_allocation_method not in self.METHODS:
            raise ShadowAllocationValidationError(f"Unsupported allocation method: {approved_allocation_method}")
        if not decision_results:
            raise ShadowAllocationValidationError("decision_results are required.")
        if not expected_return_results:
            raise ShadowAllocationValidationError("expected_return_results are required.")
        if available_shadow_cash < 0:
            raise ShadowAllocationValidationError("available_shadow_cash cannot be negative.")

        if constraints.minimum_position_weight < 0 or constraints.maximum_position_weight <= 0:
            raise ShadowAllocationValidationError("Position constraints are invalid.")
        if constraints.minimum_position_weight > constraints.maximum_position_weight:
            raise ShadowAllocationValidationError("minimum_position_weight cannot exceed maximum_position_weight.")
        if constraints.maximum_sector_weight <= 0 or constraints.maximum_sector_weight > 1:
            raise ShadowAllocationValidationError("maximum_sector_weight must be in (0,1].")
        if constraints.minimum_cash_reserve < 0 or constraints.minimum_cash_reserve >= 1:
            raise ShadowAllocationValidationError("minimum_cash_reserve must be in [0,1).")
        if constraints.maximum_number_of_holdings <= 0:
            raise ShadowAllocationValidationError("maximum_number_of_holdings must be positive.")
        if constraints.maximum_turnover < 0:
            raise ShadowAllocationValidationError("maximum_turnover cannot be negative.")
        if constraints.maximum_total_invested_capital <= 0:
            raise ShadowAllocationValidationError("maximum_total_invested_capital must be positive.")

        overlap = set(t.upper() for t in constraints.prohibited_tickers) & set(t.upper() for t in constraints.required_tickers)
        if overlap:
            raise ShadowAllocationValidationError("Constraints are inconsistent: required and prohibited overlap.")

    def _build_raw_weights(
        self,
        *,
        method: str,
        tickers: Sequence[str],
        decisions: Mapping[str, DecisionResult],
        expected: Mapping[str, ExpectedReturnResult],
        user_weights: Mapping[str, float],
    ) -> dict[str, float]:
        if method == "equal_weight":
            return {ticker: 1.0 for ticker in tickers}
        if method == "expected_return_weight":
            return {ticker: max(0.0, expected[ticker].expected_annual_return) for ticker in tickers}
        if method == "confidence_adjusted_return_weight":
            return {ticker: max(0.0, expected[ticker].confidence_adjusted_expected_return) for ticker in tickers}
        if method == "score_weight":
            return {ticker: max(0.0, decisions[ticker].research_confidence) for ticker in tickers}
        return {ticker: max(0.0, float(user_weights.get(ticker, 0.0))) for ticker in tickers}

    @staticmethod
    def _normalize(weights: Mapping[str, float]) -> dict[str, float]:
        total = sum(weights.values())
        if total <= 0:
            raise ShadowAllocationValidationError("Weights do not sum to a positive value.")
        return {ticker: value / total for ticker, value in weights.items() if value > 0}

    @staticmethod
    def _enforce_max_holdings(weights: Mapping[str, float], max_holdings: int) -> dict[str, float]:
        ranked = sorted(weights.items(), key=lambda item: (-item[1], item[0]))
        kept = dict(ranked[:max_holdings])
        return ShadowAllocationModel._normalize(kept)

    @staticmethod
    def _apply_position_limits(weights: Mapping[str, float], constraints: PortfolioConstraints, violations: list[str]) -> dict[str, float]:
        out = {ticker: min(constraints.maximum_position_weight, weight) for ticker, weight in weights.items()}
        if any(weight > constraints.maximum_position_weight for weight in weights.values()):
            violations.append("MAX_POSITION_WEIGHT_CAPPED")
        total = sum(out.values())
        if total <= 0:
            raise ShadowAllocationValidationError("All weights became zero after max-position capping.")
        out = {ticker: value / total for ticker, value in out.items()}

        below_min = [ticker for ticker, weight in out.items() if weight < constraints.minimum_position_weight]
        if below_min:
            violations.append("MIN_POSITION_WEIGHT_BREACH")
            out = {ticker: weight for ticker, weight in out.items() if weight >= constraints.minimum_position_weight}
            if not out:
                raise ShadowAllocationValidationError("No weights remain after min-position filter.")
            out = ShadowAllocationModel._normalize(out)
        return out

    @staticmethod
    def _apply_sector_limit(
        weights: Mapping[str, float],
        max_sector_weight: float,
        sector_map: Mapping[str, str],
        violations: list[str],
    ) -> dict[str, float]:
        if not sector_map:
            return dict(weights)
        sector_totals: dict[str, float] = {}
        for ticker, weight in weights.items():
            sector = sector_map.get(ticker, "UNMAPPED")
            sector_totals[sector] = sector_totals.get(sector, 0.0) + weight

        out = dict(weights)
        touched = False
        for sector, total in sorted(sector_totals.items()):
            if total <= max_sector_weight:
                continue
            touched = True
            scale = max_sector_weight / total
            for ticker in sorted(out.keys()):
                if sector_map.get(ticker, "UNMAPPED") == sector:
                    out[ticker] *= scale

        if touched:
            violations.append("MAX_SECTOR_WEIGHT_CAPPED")
            out = ShadowAllocationModel._normalize(out)
        return out

    @staticmethod
    def _turnover(current_holdings: Mapping[str, float], new_weights: Mapping[str, float], portfolio_value: float) -> float:
        if portfolio_value <= 0:
            return 0.0
        current_weights = {ticker: value / portfolio_value for ticker, value in current_holdings.items() if value > 0}
        tickers = sorted(set(current_weights.keys()) | set(new_weights.keys()))
        gross = sum(abs(new_weights.get(ticker, 0.0) - current_weights.get(ticker, 0.0)) for ticker in tickers)
        return gross * 0.5

    @staticmethod
    def _shrink_to_current(
        current_holdings: Mapping[str, float],
        target_weights: Mapping[str, float],
        portfolio_value: float,
        shrink: float,
    ) -> dict[str, float]:
        shrink = max(0.0, min(1.0, shrink))
        current_weights = {ticker: value / portfolio_value for ticker, value in current_holdings.items() if value > 0}
        tickers = sorted(set(current_weights.keys()) | set(target_weights.keys()))
        mixed = {
            ticker: current_weights.get(ticker, 0.0) + (target_weights.get(ticker, 0.0) - current_weights.get(ticker, 0.0)) * shrink
            for ticker in tickers
        }
        positive = {ticker: value for ticker, value in mixed.items() if value > 0}
        if not positive:
            return {}
        total = sum(positive.values())
        return {ticker: value / total for ticker, value in positive.items()}

    @staticmethod
    def _concentration_metrics(weights: Mapping[str, float]) -> dict[str, float]:
        if not weights:
            return {"hhi": 0.0, "top_weight": 0.0, "effective_positions": 0.0}
        values = list(weights.values())
        hhi = sum(value * value for value in values)
        effective = 0.0 if hhi == 0 else 1.0 / hhi
        return {"hhi": hhi, "top_weight": max(values), "effective_positions": effective}

    @staticmethod
    def _replacement_candidates(
        *,
        current_shadow_holdings: Mapping[str, float],
        proposed_weights: Mapping[str, float],
        expected: Mapping[str, ExpectedReturnResult],
        constraints: PortfolioConstraints,
        portfolio_value: float,
    ) -> tuple[ReplacementEvaluation, ...]:
        current_weights = {ticker: value / portfolio_value for ticker, value in current_shadow_holdings.items() if value > 0}
        incumbents = sorted([ticker for ticker in current_weights if ticker not in proposed_weights])
        candidates = sorted([ticker for ticker in proposed_weights if ticker not in current_weights])
        out: list[ReplacementEvaluation] = []
        candidate_pool = list(candidates)
        for incumbent in incumbents:
            if not candidate_pool:
                break
            candidate = candidate_pool.pop(0)
            incumbent_er = expected[incumbent].expected_annual_return if incumbent in expected else 0.0
            incumbent_ca = expected[incumbent].confidence_adjusted_expected_return if incumbent in expected else 0.0
            candidate_er = expected[candidate].expected_annual_return
            candidate_ca = expected[candidate].confidence_adjusted_expected_return
            est_turnover = abs(current_weights.get(incumbent, 0.0)) + abs(proposed_weights.get(candidate, 0.0))
            blocks: list[str] = []
            if candidate.upper() in {t.upper() for t in constraints.prohibited_tickers}:
                blocks.append("PROHIBITED")
            if est_turnover > constraints.maximum_turnover:
                blocks.append("TURNOVER_HIGH")
            out.append(
                ReplacementEvaluation(
                    incumbent_ticker=incumbent,
                    candidate_ticker=candidate,
                    expected_return_improvement=candidate_er - incumbent_er,
                    confidence_adjusted_improvement=candidate_ca - incumbent_ca,
                    estimated_turnover=est_turnover,
                    constraint_impact={"max_turnover": constraints.maximum_turnover},
                    eligibility_status=len(blocks) == 0,
                    blocking_reasons=tuple(blocks),
                )
            )
        out.sort(
            key=lambda row: (
                -(row.confidence_adjusted_improvement),
                -(row.expected_return_improvement),
                row.incumbent_ticker,
                row.candidate_ticker,
            )
        )
        return tuple(out)

    @staticmethod
    def _configuration_hash(
        *,
        method: str,
        constraints: PortfolioConstraints,
        deterministic_record: Mapping[str, Any],
        user_weights: Mapping[str, float],
        sector_map: Mapping[str, str],
    ) -> str:
        payload = (
            f"{method}|{constraints}|{sorted(deterministic_record.items())}|"
            f"{sorted(user_weights.items())}|{sorted(sector_map.items())}"
        )
        return sha256(payload.encode("utf-8")).hexdigest()
