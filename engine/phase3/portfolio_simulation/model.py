from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import sqrt
from statistics import mean
from typing import Any, Mapping, Sequence

from engine.phase3.decision_engine.model import DecisionResult
from engine.phase3.expected_return.model import ExpectedReturnResult

from .types import BacktestResult, SimulationAudit, SimulationAuditStep, SimulationScenario


class SimulationValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SimulationResult:
    simulated_cagr: float
    volatility: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    turnover: float
    concentration_metrics: Mapping[str, float]
    cash_utilization: float
    simulation_audit: SimulationAudit
    backtest_result: BacktestResult


class SimulationModel:
    SUPPORTED_METHODS = ("equal_weight", "score_weight", "confidence_weight", "user_defined")

    def evaluate(
        self,
        *,
        decision_outputs: Sequence[DecisionResult],
        expected_returns: Mapping[str, ExpectedReturnResult],
        allocation_scenario: SimulationScenario,
        historical_returns: Mapping[str, Sequence[float]],
        start_date: str,
        end_date: str,
        benchmark: str,
        benchmark_returns: Sequence[float] | None = None,
    ) -> SimulationResult:
        steps: list[SimulationAuditStep] = []
        self._validate_inputs(decision_outputs, expected_returns, allocation_scenario, historical_returns)

        tickers = sorted(self._eligible_tickers(decision_outputs, expected_returns, historical_returns))
        if not tickers:
            raise SimulationValidationError("No eligible tickers are available for simulation.")

        steps.append(
            SimulationAuditStep(
                step="eligible_universe",
                passed=True,
                detail="Filtered eligible tickers from decision outputs.",
                timestamp=end_date,
                record={"tickers": tuple(tickers)},
            )
        )

        weights = self._build_weights(tickers, decision_outputs, expected_returns, allocation_scenario)
        steps.append(
            SimulationAuditStep(
                step="allocation_weights",
                passed=True,
                detail=f"Built deterministic weights using {allocation_scenario.method}.",
                timestamp=end_date,
                record={"weights": dict(weights)},
            )
        )

        portfolio_returns = self._portfolio_returns(tickers, weights, historical_returns)
        if not portfolio_returns:
            raise SimulationValidationError("No portfolio returns were generated.")

        periods_per_year = int(allocation_scenario.assumptions.get("periods_per_year", 252))
        risk_free_rate = float(allocation_scenario.assumptions.get("risk_free_rate", 0.0))
        cagr = self._cagr(portfolio_returns, periods_per_year)
        volatility = self._annualized_volatility(portfolio_returns, periods_per_year)
        max_drawdown = self._max_drawdown(portfolio_returns)
        sharpe = self._sharpe(portfolio_returns, periods_per_year, risk_free_rate)
        sortino = self._sortino(portfolio_returns, periods_per_year, risk_free_rate)
        hit_rate = self._hit_rate(portfolio_returns)
        turnover = self._turnover(weights)
        concentration = self._concentration_metrics(weights)
        cash_utilization = min(1.0, max(0.0, sum(weights.values())))

        steps.append(
            SimulationAuditStep(
                step="metric_calculation",
                passed=True,
                detail="Computed simulation analytics.",
                timestamp=end_date,
                record={
                    "simulated_cagr": cagr,
                    "volatility": volatility,
                    "max_drawdown": max_drawdown,
                    "sharpe_ratio": sharpe,
                    "sortino_ratio": sortino,
                    "hit_rate": hit_rate,
                    "turnover": turnover,
                    "cash_utilization": cash_utilization,
                },
            )
        )

        deterministic_record = {
            "tickers": tuple(tickers),
            "weights": tuple((t, weights[t]) for t in tickers),
            "periods": len(portfolio_returns),
            "method": allocation_scenario.method,
            "benchmark": benchmark,
            "benchmark_points": len(benchmark_returns or ()),
        }
        config_hash = self._configuration_hash(
            start_date=start_date,
            end_date=end_date,
            benchmark=benchmark,
            deterministic_record=deterministic_record,
            assumptions=allocation_scenario.assumptions,
        )
        audit = SimulationAudit(
            assumptions=dict(allocation_scenario.assumptions),
            validation_steps=tuple(steps),
            timestamp=end_date,
            deterministic_execution_record=deterministic_record,
            configuration_hash=config_hash,
        )

        backtest = BacktestResult(
            start_date=start_date,
            end_date=end_date,
            benchmark=benchmark,
            cagr=cagr,
            annual_volatility=volatility,
            max_drawdown=max_drawdown,
            sharpe=sharpe,
            sortino=sortino,
            hit_rate=hit_rate,
            turnover=turnover,
            audit=audit,
        )

        return SimulationResult(
            simulated_cagr=cagr,
            volatility=volatility,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            turnover=turnover,
            concentration_metrics=concentration,
            cash_utilization=cash_utilization,
            simulation_audit=audit,
            backtest_result=backtest,
        )

    def _validate_inputs(
        self,
        decision_outputs: Sequence[DecisionResult],
        expected_returns: Mapping[str, ExpectedReturnResult],
        allocation_scenario: SimulationScenario,
        historical_returns: Mapping[str, Sequence[float]],
    ) -> None:
        if not decision_outputs:
            raise SimulationValidationError("decision_outputs are required.")
        if not expected_returns:
            raise SimulationValidationError("expected_returns are required.")
        if not historical_returns:
            raise SimulationValidationError("historical_returns are required.")
        if allocation_scenario.method not in self.SUPPORTED_METHODS:
            raise SimulationValidationError(f"Unsupported simulation method: {allocation_scenario.method}")

    @staticmethod
    def _eligible_tickers(
        decision_outputs: Sequence[DecisionResult],
        expected_returns: Mapping[str, ExpectedReturnResult],
        historical_returns: Mapping[str, Sequence[float]],
    ) -> set[str]:
        eligible = {
            decision.ticker
            for decision in decision_outputs
            if decision.decision_eligible
            and decision.ticker in expected_returns
            and decision.ticker in historical_returns
        }
        return eligible

    def _build_weights(
        self,
        tickers: Sequence[str],
        decision_outputs: Sequence[DecisionResult],
        expected_returns: Mapping[str, ExpectedReturnResult],
        scenario: SimulationScenario,
    ) -> dict[str, float]:
        decision_map = {decision.ticker: decision for decision in decision_outputs}

        if scenario.method == "equal_weight":
            raw = {ticker: 1.0 for ticker in tickers}
        elif scenario.method == "score_weight":
            raw = {ticker: max(0.0, decision_map[ticker].confidence_adjusted_expected_return) for ticker in tickers}
        elif scenario.method == "confidence_weight":
            raw = {ticker: max(0.0, decision_map[ticker].research_confidence) for ticker in tickers}
        else:
            raw = {ticker: float(scenario.user_weights.get(ticker, 0.0)) for ticker in tickers}

        total = sum(raw.values())
        if total <= 0:
            raise SimulationValidationError("Allocation weights must sum to a positive value.")
        return {ticker: raw[ticker] / total for ticker in tickers}

    @staticmethod
    def _portfolio_returns(tickers: Sequence[str], weights: Mapping[str, float], historical_returns: Mapping[str, Sequence[float]]) -> list[float]:
        series_lengths = [len(historical_returns[ticker]) for ticker in tickers]
        if not series_lengths or min(series_lengths) == 0:
            return []
        periods = min(series_lengths)
        out: list[float] = []
        for i in range(periods):
            out.append(sum(weights[ticker] * float(historical_returns[ticker][i]) for ticker in tickers))
        return out

    @staticmethod
    def _cagr(returns: Sequence[float], periods_per_year: int) -> float:
        cumulative = 1.0
        for value in returns:
            cumulative *= 1.0 + value
        years = max(1e-9, len(returns) / max(1, periods_per_year))
        return pow(max(1e-12, cumulative), 1.0 / years) - 1.0

    @staticmethod
    def _annualized_volatility(returns: Sequence[float], periods_per_year: int) -> float:
        if len(returns) < 2:
            return 0.0
        avg = mean(returns)
        variance = mean([(value - avg) ** 2 for value in returns])
        return sqrt(max(0.0, variance)) * sqrt(periods_per_year)

    @staticmethod
    def _max_drawdown(returns: Sequence[float]) -> float:
        equity = 1.0
        peak = 1.0
        max_dd = 0.0
        for value in returns:
            equity *= 1.0 + value
            peak = max(peak, equity)
            dd = (equity / peak) - 1.0
            max_dd = min(max_dd, dd)
        return abs(max_dd)

    @staticmethod
    def _sharpe(returns: Sequence[float], periods_per_year: int, risk_free_rate: float) -> float:
        if not returns:
            return 0.0
        annual_return = mean(returns) * periods_per_year
        vol = SimulationModel._annualized_volatility(returns, periods_per_year)
        if vol == 0:
            return 0.0
        return (annual_return - risk_free_rate) / vol

    @staticmethod
    def _sortino(returns: Sequence[float], periods_per_year: int, risk_free_rate: float) -> float:
        if not returns:
            return 0.0
        annual_return = mean(returns) * periods_per_year
        downside = [min(0.0, value) for value in returns]
        if not downside:
            return 0.0
        downside_dev = sqrt(mean([value * value for value in downside])) * sqrt(periods_per_year)
        if downside_dev == 0:
            return 0.0
        return (annual_return - risk_free_rate) / downside_dev

    @staticmethod
    def _hit_rate(returns: Sequence[float]) -> float:
        if not returns:
            return 0.0
        wins = sum(1 for value in returns if value > 0)
        return wins / len(returns)

    @staticmethod
    def _turnover(weights: Mapping[str, float]) -> float:
        return sum(abs(value) for value in weights.values())

    @staticmethod
    def _concentration_metrics(weights: Mapping[str, float]) -> dict[str, float]:
        if not weights:
            return {"hhi": 0.0, "top_weight": 0.0, "effective_positions": 0.0}
        values = list(weights.values())
        hhi = sum(value * value for value in values)
        effective_positions = 0.0 if hhi == 0 else 1.0 / hhi
        return {
            "hhi": hhi,
            "top_weight": max(values),
            "effective_positions": effective_positions,
        }

    @staticmethod
    def _configuration_hash(
        *,
        start_date: str,
        end_date: str,
        benchmark: str,
        deterministic_record: Mapping[str, Any],
        assumptions: Mapping[str, Any],
    ) -> str:
        payload = f"{start_date}|{end_date}|{benchmark}|{sorted(deterministic_record.items())}|{sorted(assumptions.items())}"
        return sha256(payload.encode("utf-8")).hexdigest()
