from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from engine.phase3.paper_portfolio_governance.policy import PaperRecommendationPolicy
from engine.phase3.paper_portfolio_governance.types import (
    PaperPortfolioState,
    PaperRecommendationRecord,
    PaperRecommendationStatus,
)

from .types import (
    EngineAuditStep,
    PaperPortfolioAudit,
    PaperPortfolioEngineResult,
    PaperTransaction,
    PerformanceSnapshot,
    PositionRecord,
)


class PaperPortfolioEngineValidationError(ValueError):
    pass


class PaperPortfolioEngine:
    SOURCE_MODULES = (
        "engine.phase3.paper_portfolio_governance.types",
        "engine.phase3.paper_portfolio_governance.policy",
        "engine.phase3.paper_portfolio_engine.types",
        "engine.phase3.paper_portfolio_engine.model",
    )

    def evaluate(
        self,
        *,
        recommendation_records: Sequence[PaperRecommendationRecord],
        paper_portfolio_state: PaperPortfolioState,
        policy: PaperRecommendationPolicy,
        historical_market_prices: Mapping[str, Mapping[str, float]],
        benchmark_prices: Mapping[str, float],
        as_of_timestamp: str,
        slippage_assumption: float = 0.001,
        commission_per_dollar: float = 0.0,
        recommendation_audit_valid: bool = True,
        production_portfolio_access_attempted: bool = False,
        broker_access_attempted: bool = False,
    ) -> PaperPortfolioEngineResult:
        steps: list[EngineAuditStep] = []
        self._fail_closed(
            recommendation_audit_valid=recommendation_audit_valid,
            production_portfolio_access_attempted=production_portfolio_access_attempted,
            broker_access_attempted=broker_access_attempted,
        )
        policy.validate()
        self._validate_inputs(
            recommendation_records=recommendation_records,
            paper_portfolio_state=paper_portfolio_state,
            historical_market_prices=historical_market_prices,
            benchmark_prices=benchmark_prices,
            slippage_assumption=slippage_assumption,
            commission_per_dollar=commission_per_dollar,
        )

        steps.append(
            EngineAuditStep(
                step="input_validation",
                passed=True,
                detail="Input contracts and fail-closed guards passed.",
                timestamp=as_of_timestamp,
            )
        )

        nav_before = float(paper_portfolio_state.total_paper_value)
        cash = float(paper_portfolio_state.paper_cash)
        holdings_value = nav_before - cash

        current_positions = {k.upper(): float(v) for k, v in paper_portfolio_state.paper_holdings.items()}
        current_weights = {k.upper(): float(v) for k, v in paper_portfolio_state.paper_weights.items()}

        by_ticker: dict[str, PaperRecommendationRecord] = {}
        blocked: dict[str, tuple[str, ...]] = {}
        executed: list[str] = []

        for record in recommendation_records:
            self._validate_recommendation(record)
            ticker = record.ticker.upper()
            if record.status is PaperRecommendationStatus.APPROVED_FOR_PAPER:
                by_ticker[ticker] = record
            else:
                blocked[ticker] = tuple(sorted(set(record.blocking_reasons + ("NOT_APPROVED_FOR_PAPER",))))

        fills: list[PaperTransaction] = []
        updated_holdings_value: dict[str, float] = dict(current_positions)

        for ticker in sorted(set(updated_holdings_value.keys()) | set(by_ticker.keys())):
            current_value = float(updated_holdings_value.get(ticker, 0.0))
            current_weight = float(current_weights.get(ticker, 0.0))
            record = by_ticker.get(ticker)
            if record is None:
                continue

            if record.status in (PaperRecommendationStatus.BLOCKED, PaperRecommendationStatus.EXPIRED):
                blocked[ticker] = tuple(sorted(set(record.blocking_reasons + ("STATUS_NOT_EXECUTABLE",))))
                continue

            if ticker in {t.upper() for t in policy.prohibited_tickers}:
                blocked[ticker] = tuple(sorted(set(record.blocking_reasons + ("PROHIBITED_TICKER",))))
                continue

            target_weight = float(record.proposed_paper_weight)
            if target_weight < 0.0 or target_weight > policy.maximum_position_weight + 1e-12:
                blocked[ticker] = tuple(sorted(set(record.blocking_reasons + ("POSITION_WEIGHT_POLICY_BREACH",))))
                continue

            if target_weight > 0.0 and current_weight == 0.0 and len([v for v in updated_holdings_value.values() if v > 0]) >= policy.maximum_number_of_holdings:
                blocked[ticker] = tuple(sorted(set(record.blocking_reasons + ("MAX_HOLDINGS_POLICY_BREACH",))))
                continue

            price = self._price_for(historical_market_prices, ticker, as_of_timestamp)
            target_value = nav_before * target_weight
            delta_value = target_value - current_value
            if abs(delta_value) < 1e-9:
                continue

            side = "BUY" if delta_value > 0 else "SELL"
            execution_price = price * (1.0 + slippage_assumption if side == "BUY" else 1.0 - slippage_assumption)
            shares = abs(delta_value) / execution_price
            gross_dollars = shares * execution_price
            commission = gross_dollars * commission_per_dollar
            signed_dollars = gross_dollars + commission if side == "BUY" else -(gross_dollars - commission)

            if side == "BUY" and signed_dollars > cash + 1e-9:
                blocked[ticker] = tuple(sorted(set(record.blocking_reasons + ("INSUFFICIENT_CASH",))))
                continue

            cash -= signed_dollars
            updated_holdings_value[ticker] = current_value + (gross_dollars if side == "BUY" else -gross_dollars)
            if updated_holdings_value[ticker] <= 1e-9:
                updated_holdings_value[ticker] = 0.0

            tx_id = self._transaction_id(
                recommendation_id=record.recommendation_id,
                ticker=ticker,
                timestamp=as_of_timestamp,
                side=side,
                price=execution_price,
                shares=shares,
                dollars=signed_dollars,
                slippage_assumption=slippage_assumption,
                commission=commission,
            )
            fills.append(
                PaperTransaction(
                    transaction_id=tx_id,
                    recommendation_id=record.recommendation_id,
                    timestamp=as_of_timestamp,
                    simulated_execution_price=execution_price,
                    shares=shares,
                    dollars=signed_dollars,
                    commission=commission,
                    slippage_assumption=slippage_assumption,
                    transaction_type=side,
                    audit_reference=record.source_audit_references.get("decision", "deterministic"),
                )
            )
            executed.append(record.recommendation_id)

        holdings_value_after = {k: v for k, v in sorted(updated_holdings_value.items()) if v > 0.0}
        invested_after = sum(holdings_value_after.values())
        nav_after = invested_after + cash
        if nav_after <= 0:
            raise PaperPortfolioEngineValidationError("Portfolio NAV must remain positive.")

        weights_after = {ticker: value / nav_after for ticker, value in holdings_value_after.items()}
        if any(weight > policy.maximum_position_weight + 1e-12 for weight in weights_after.values()):
            raise PaperPortfolioEngineValidationError("Post-fill position weight exceeds policy maximum.")
        if len(weights_after) > policy.maximum_number_of_holdings:
            raise PaperPortfolioEngineValidationError("Post-fill holdings count exceeds policy maximum.")

        cash_weight = cash / nav_after
        if cash_weight + 1e-12 < policy.minimum_cash_reserve:
            raise PaperPortfolioEngineValidationError("Cash reserve below policy minimum.")

        turnover = self._turnover(current_positions, holdings_value_after, nav_before)
        if turnover > policy.maximum_portfolio_turnover + 1e-12:
            raise PaperPortfolioEngineValidationError("Portfolio turnover exceeds policy maximum.")

        realized_pnl = sum(-tx.commission for tx in fills)
        unrealized_pnl = invested_after - holdings_value

        benchmark_return = self._benchmark_return(benchmark_prices)
        cumulative_return = (nav_after / nav_before) - 1.0 if nav_before > 0 else 0.0
        daily_return = cumulative_return
        active_return = cumulative_return - benchmark_return
        drawdown = min(0.0, cumulative_return)
        concentration = max(weights_after.values()) if weights_after else 0.0

        audit_ref = self._hash_payload(
            {
                "fills": [asdict(tx) for tx in fills],
                "nav_after": nav_after,
                "benchmark_return": benchmark_return,
                "timestamp": as_of_timestamp,
            }
        )

        snapshot = PerformanceSnapshot(
            timestamp=as_of_timestamp,
            nav=nav_after,
            cash=cash,
            invested_capital=invested_after,
            daily_return=daily_return,
            cumulative_return=cumulative_return,
            benchmark_return=benchmark_return,
            active_return=active_return,
            drawdown=drawdown,
            turnover=turnover,
            concentration=concentration,
            audit_reference=audit_ref,
        )

        positions = tuple(
            PositionRecord(
                ticker=ticker,
                quantity=holdings_value_after[ticker] / self._price_for(historical_market_prices, ticker, as_of_timestamp),
                average_cost=self._price_for(historical_market_prices, ticker, as_of_timestamp),
                current_price=self._price_for(historical_market_prices, ticker, as_of_timestamp),
                market_value=holdings_value_after[ticker],
                unrealized_gain_loss=holdings_value_after[ticker] - current_positions.get(ticker, 0.0),
                realized_gain_loss=0.0,
                cost_basis=holdings_value_after[ticker],
                weight=weights_after[ticker],
                first_purchase_date=paper_portfolio_state.as_of_timestamp,
                last_update=as_of_timestamp,
                provenance={"source": "paper_portfolio_engine"},
            )
            for ticker in sorted(holdings_value_after)
        )

        steps.extend(
            (
                EngineAuditStep(
                    step="fill_simulation",
                    passed=True,
                    detail="Deterministic simulated fills completed.",
                    timestamp=as_of_timestamp,
                    record={"fill_count": len(fills)},
                ),
                EngineAuditStep(
                    step="reconciliation",
                    passed=True,
                    detail="Portfolio reconciliation balanced with policy constraints.",
                    timestamp=as_of_timestamp,
                    record={"cash_weight": cash_weight, "turnover": turnover},
                ),
                EngineAuditStep(
                    step="performance_snapshot",
                    passed=True,
                    detail="Deterministic portfolio performance metrics computed.",
                    timestamp=as_of_timestamp,
                    record={"nav": nav_after, "cumulative_return": cumulative_return},
                ),
            )
        )

        input_hashes = {
            "recommendations": self._hash_payload([asdict(row) for row in recommendation_records]),
            "state": self._hash_payload(asdict(paper_portfolio_state)),
            "policy": self._hash_payload(asdict(policy)),
            "prices": self._hash_payload(historical_market_prices),
            "benchmark": self._hash_payload(benchmark_prices),
        }

        deterministic_record = {
            "executed_transaction_ids": tuple(tx.transaction_id for tx in fills),
            "executed_recommendations": tuple(sorted(executed)),
            "nav_after": nav_after,
            "cash_after": cash,
            "timestamp": as_of_timestamp,
        }

        config_hash = self._hash_payload(
            {
                "input_hashes": input_hashes,
                "deterministic_record": deterministic_record,
                "slippage": slippage_assumption,
                "commission_rate": commission_per_dollar,
            }
        )

        audit = PaperPortfolioAudit(
            source_modules=self.SOURCE_MODULES,
            input_hashes=input_hashes,
            validation_steps=tuple(steps),
            executed_recommendations=tuple(sorted(executed)),
            rejected_recommendations=tuple(sorted(blocked.keys())),
            blocking_reasons=blocked,
            reconciliation_ok=True,
            configuration_hash=config_hash,
            deterministic_execution_record=deterministic_record,
            timestamp_metadata={"as_of": as_of_timestamp, "created": as_of_timestamp},
        )

        updated_state = PaperPortfolioState(
            as_of_timestamp=as_of_timestamp,
            paper_cash=cash,
            paper_holdings=holdings_value_after,
            paper_weights=weights_after,
            total_paper_value=nav_after,
            provenance={"source": "paper_portfolio_engine", "audit": config_hash},
            version=paper_portfolio_state.version,
        )

        return PaperPortfolioEngineResult(
            updated_state=updated_state,
            simulated_fills=tuple(fills),
            positions=positions,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            cash_balance=cash,
            holdings=holdings_value_after,
            transaction_history=tuple(fills),
            portfolio_nav=nav_after,
            benchmark_comparison={
                "portfolio_return": cumulative_return,
                "benchmark_return": benchmark_return,
                "active_return": active_return,
            },
            performance_snapshot=snapshot,
            portfolio_audit=audit,
        )

    @staticmethod
    def _validate_inputs(
        *,
        recommendation_records: Sequence[PaperRecommendationRecord],
        paper_portfolio_state: PaperPortfolioState,
        historical_market_prices: Mapping[str, Mapping[str, float]],
        benchmark_prices: Mapping[str, float],
        slippage_assumption: float,
        commission_per_dollar: float,
    ) -> None:
        if not recommendation_records:
            raise PaperPortfolioEngineValidationError("recommendation_records are required.")
        if not isinstance(paper_portfolio_state, PaperPortfolioState):
            raise PaperPortfolioEngineValidationError("paper_portfolio_state must be PaperPortfolioState.")
        if not historical_market_prices:
            raise PaperPortfolioEngineValidationError("historical_market_prices are required.")
        if not benchmark_prices:
            raise PaperPortfolioEngineValidationError("benchmark_prices are required.")
        if slippage_assumption < 0.0:
            raise PaperPortfolioEngineValidationError("slippage_assumption cannot be negative.")
        if commission_per_dollar < 0.0:
            raise PaperPortfolioEngineValidationError("commission_per_dollar cannot be negative.")

    @staticmethod
    def _validate_recommendation(record: PaperRecommendationRecord) -> None:
        if record.status not in (
            PaperRecommendationStatus.DRAFT,
            PaperRecommendationStatus.BLOCKED,
            PaperRecommendationStatus.PENDING_APPROVAL,
            PaperRecommendationStatus.APPROVED_FOR_PAPER,
            PaperRecommendationStatus.REJECTED,
            PaperRecommendationStatus.EXPIRED,
            PaperRecommendationStatus.SUPERSEDED,
        ):
            raise PaperPortfolioEngineValidationError("Recommendation status is invalid.")
        if not record.recommendation_id or not record.source_audit_references:
            raise PaperPortfolioEngineValidationError("Recommendation audit reference is invalid.")

    @staticmethod
    def _fail_closed(
        *,
        recommendation_audit_valid: bool,
        production_portfolio_access_attempted: bool,
        broker_access_attempted: bool,
    ) -> None:
        if not recommendation_audit_valid:
            raise PaperPortfolioEngineValidationError("Recommendation audit is invalid.")
        if production_portfolio_access_attempted:
            raise PaperPortfolioEngineValidationError("Production portfolio access is not permitted.")
        if broker_access_attempted:
            raise PaperPortfolioEngineValidationError("Broker access is not permitted.")

    @staticmethod
    def _price_for(prices: Mapping[str, Mapping[str, float]], ticker: str, timestamp: str) -> float:
        ticker_prices = prices.get(ticker)
        if not ticker_prices:
            raise PaperPortfolioEngineValidationError(f"Historical pricing unavailable for {ticker}.")
        if timestamp in ticker_prices:
            price = float(ticker_prices[timestamp])
        elif "default" in ticker_prices:
            price = float(ticker_prices["default"])
        else:
            raise PaperPortfolioEngineValidationError(f"Historical pricing unavailable for {ticker} at {timestamp}.")
        if price <= 0:
            raise PaperPortfolioEngineValidationError(f"Invalid price for {ticker}.")
        return price

    @staticmethod
    def _benchmark_return(benchmark_prices: Mapping[str, float]) -> float:
        if "start" not in benchmark_prices or "end" not in benchmark_prices:
            raise PaperPortfolioEngineValidationError("Benchmark prices require start and end values.")
        start = float(benchmark_prices["start"])
        end = float(benchmark_prices["end"])
        if start <= 0:
            raise PaperPortfolioEngineValidationError("Benchmark start price must be positive.")
        return (end / start) - 1.0

    @staticmethod
    def _turnover(before: Mapping[str, float], after: Mapping[str, float], nav_before: float) -> float:
        if nav_before <= 0:
            return 0.0
        tickers = set(before) | set(after)
        total_change = sum(abs(float(after.get(t, 0.0)) - float(before.get(t, 0.0))) for t in tickers)
        return min(1.0, total_change / max(nav_before, 1e-12))

    @staticmethod
    def _transaction_id(
        *,
        recommendation_id: str,
        ticker: str,
        timestamp: str,
        side: str,
        price: float,
        shares: float,
        dollars: float,
        slippage_assumption: float,
        commission: float,
    ) -> str:
        payload = (
            f"{recommendation_id}|{ticker}|{timestamp}|{side}|{price:.12f}|{shares:.12f}|{dollars:.12f}|"
            f"{slippage_assumption:.12f}|{commission:.12f}"
        )
        return "PTX-" + sha256(payload.encode("utf-8")).hexdigest()[:16].upper()

    @staticmethod
    def _hash_payload(payload: Any) -> str:
        return sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()
