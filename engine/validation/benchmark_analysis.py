from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from statistics import mean, pstdev

from .historical_replay import HistoricalReplayResult


@dataclass(frozen=True)
class BenchmarkAnalysisResult:
    alpha_vs_spy: float
    alpha_vs_equal_weight: float
    alpha_vs_benchmark_portfolio: float
    hit_rate: float
    sharpe: float
    sortino: float
    max_drawdown: float
    turnover: float
    average_holding_period: float
    sector_attribution: tuple[tuple[str, float], ...] = field(default_factory=tuple)


def _safe_mean(values: list[float]) -> float:
    return mean(values) if values else 0.0


def _sharpe(returns: list[float]) -> float:
    if not returns:
        return 0.0
    volatility = pstdev(returns)
    if volatility == 0:
        return 0.0
    return _safe_mean(returns) / volatility


def _sortino(returns: list[float]) -> float:
    if not returns:
        return 0.0
    downside = [value for value in returns if value < 0.0]
    downside_vol = pstdev(downside) if len(downside) > 1 else (abs(downside[0]) if downside else 0.0)
    if downside_vol == 0:
        return 0.0
    return _safe_mean(returns) / downside_vol


def _max_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        drawdown = (equity / peak) - 1.0
        max_dd = min(max_dd, drawdown)
    return abs(max_dd)


def analyze_benchmarks(replay: HistoricalReplayResult) -> BenchmarkAnalysisResult:
    points = list(replay.points)
    if not points:
        return BenchmarkAnalysisResult(
            alpha_vs_spy=0.0,
            alpha_vs_equal_weight=0.0,
            alpha_vs_benchmark_portfolio=0.0,
            hit_rate=0.0,
            sharpe=0.0,
            sortino=0.0,
            max_drawdown=0.0,
            turnover=0.0,
            average_holding_period=0.0,
            sector_attribution=(),
        )

    cio_returns = [point.cio_return for point in points]
    spy_returns = [point.spy_return for point in points]
    equal_returns = [point.equal_weight_return for point in points]
    benchmark_returns = [point.benchmark_return for point in points]

    alpha_vs_spy = _safe_mean([cio - spy for cio, spy in zip(cio_returns, spy_returns)])
    alpha_vs_equal = _safe_mean([cio - eq for cio, eq in zip(cio_returns, equal_returns)])
    alpha_vs_bench = _safe_mean([cio - bench for cio, bench in zip(cio_returns, benchmark_returns)])

    hit_rate = sum(1 for value in cio_returns if value > 0.0) / len(cio_returns)
    turnover = _safe_mean([point.turnover for point in points])
    average_holding_period = _safe_mean([point.average_holding_period for point in points])

    sector_accumulator: dict[str, list[float]] = {}
    for point in points:
        for sector, value in point.sector_returns:
            sector_accumulator.setdefault(sector, []).append(float(value))
    sector_attribution = tuple(
        sorted(
            ((sector, round(_safe_mean(values), 6)) for sector, values in sector_accumulator.items()),
            key=lambda item: item[0],
        )
    )

    return BenchmarkAnalysisResult(
        alpha_vs_spy=round(alpha_vs_spy, 6),
        alpha_vs_equal_weight=round(alpha_vs_equal, 6),
        alpha_vs_benchmark_portfolio=round(alpha_vs_bench, 6),
        hit_rate=round(hit_rate, 6),
        sharpe=round(_sharpe(cio_returns) * sqrt(252), 6),
        sortino=round(_sortino(cio_returns) * sqrt(252), 6),
        max_drawdown=round(_max_drawdown(cio_returns), 6),
        turnover=round(turnover, 6),
        average_holding_period=round(average_holding_period, 6),
        sector_attribution=sector_attribution,
    )
