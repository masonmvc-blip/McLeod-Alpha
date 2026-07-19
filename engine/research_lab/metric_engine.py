from __future__ import annotations

from math import sqrt
from typing import Sequence


METRICS = ("CAGR", "annual_alpha", "Sharpe", "Sortino", "Information_Ratio", "Max_Drawdown", "Win_Rate", "Hit_Rate", "Turnover", "Average_Holding_Period", "Exposure", "Volatility", "Tracking_Error")


def calculate_metrics(returns: Sequence[float], signals: Sequence[float], benchmark: Sequence[float] | None = None) -> dict[str, float]:
    values, factors = [float(value) for value in returns], [float(value) for value in signals]
    if not values or len(values) != len(factors):
        raise ValueError("returns and signals must be non-empty and aligned")
    bench = [0.0] * len(values) if benchmark is None else [float(value) for value in benchmark]
    strategy = [value * signal for value, signal in zip(values, factors)]
    mean = sum(strategy) / len(strategy)
    volatility = _std(strategy)
    excess = [value - reference for value, reference in zip(strategy, bench)]
    downside = _std([min(0.0, value) for value in strategy])
    equity, peak, drawdown = 1.0, 1.0, 0.0
    for value in strategy:
        equity *= 1.0 + value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1.0)
    changes = sum(1 for left, right in zip(factors, factors[1:]) if left != right)
    return {"CAGR": equity ** (252.0 / len(strategy)) - 1.0, "annual_alpha": mean * 252.0, "Sharpe": mean / volatility * sqrt(252.0) if volatility else 0.0, "Sortino": mean / downside * sqrt(252.0) if downside else 0.0, "Information_Ratio": _mean(excess) / _std(excess) * sqrt(252.0) if _std(excess) else 0.0, "Max_Drawdown": drawdown, "Win_Rate": sum(value > 0 for value in strategy) / len(strategy), "Hit_Rate": sum(value * signal > 0 for value, signal in zip(values, factors)) / len(strategy), "Turnover": changes / max(1, len(factors) - 1), "Average_Holding_Period": len(strategy) / max(1, changes + 1), "Exposure": sum(abs(value) for value in factors) / len(factors), "Volatility": volatility * sqrt(252.0), "Tracking_Error": _std(excess) * sqrt(252.0)}


def _mean(values: Sequence[float]) -> float: return sum(values) / len(values)
def _std(values: Sequence[float]) -> float:
    if len(values) < 2: return 0.0
    mean = _mean(values)
    return sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))