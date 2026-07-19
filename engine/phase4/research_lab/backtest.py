from __future__ import annotations

import math
from typing import Mapping, Sequence

from .types import PerformanceMetrics


def _safe_mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mu = _safe_mean(values)
    var = sum((x - mu) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(max(0.0, var))


def _max_drawdown(returns: Sequence[float]) -> tuple[float, int]:
    curve = 1.0
    peak = 1.0
    max_dd = 0.0
    trough_index = 0
    recovery_time = 0
    last_peak_index = 0
    for i, r in enumerate(returns):
        curve *= (1.0 + float(r))
        if curve > peak:
            peak = curve
            last_peak_index = i
        dd = (curve / peak) - 1.0
        if dd < max_dd:
            max_dd = dd
            trough_index = i
            recovery_time = max(0, trough_index - last_peak_index)
    return max_dd, recovery_time


def run_backtest(
    *,
    experiment_id: str,
    factor_returns: Mapping[str, Sequence[float]],
    benchmark_returns: Sequence[float],
    periods_per_year: float = 252.0,
) -> dict[str, object]:
    if not factor_returns:
        raise ValueError("factor_returns cannot be empty")
    min_len = min(len(v) for v in factor_returns.values())
    if min_len == 0:
        raise ValueError("factor returns must have non-zero length")
    strategy_returns: list[float] = []
    factor_keys = sorted(factor_returns.keys())
    for i in range(min_len):
        strategy_returns.append(_safe_mean([float(factor_returns[k][i]) for k in factor_keys]))

    bench = [float(x) for x in benchmark_returns[:min_len]]
    strat = strategy_returns
    annualization = float(periods_per_year)
    avg = _safe_mean(strat)
    vol = _safe_stdev(strat)
    downside = _safe_stdev([min(0.0, x) for x in strat])
    benchmark_avg = _safe_mean(bench)

    cumulative = 1.0
    for r in strat:
        cumulative *= (1.0 + r)
    years = max(1.0 / annualization, len(strat) / annualization)
    cagr = cumulative ** (1.0 / years) - 1.0

    covariance = 0.0
    if len(strat) > 1 and len(bench) > 1:
        s_mu = _safe_mean(strat)
        b_mu = _safe_mean(bench)
        covariance = sum((s - s_mu) * (b - b_mu) for s, b in zip(strat, bench)) / (len(strat) - 1)
    bench_var = _safe_stdev(bench) ** 2
    beta = covariance / bench_var if bench_var > 1e-12 else 0.0
    alpha = (avg - beta * benchmark_avg) * annualization

    sharpe = (avg / vol) * math.sqrt(annualization) if vol > 1e-12 else 0.0
    sortino = (avg / downside) * math.sqrt(annualization) if downside > 1e-12 else 0.0
    active = [s - b for s, b in zip(strat, bench)]
    ir_denom = _safe_stdev(active)
    info_ratio = (_safe_mean(active) / ir_denom) * math.sqrt(annualization) if ir_denom > 1e-12 else 0.0

    max_dd, recovery = _max_drawdown(strat)
    wins = [r for r in strat if r > 0.0]
    hit_rate = len(wins) / len(strat)
    turnover = min(1.0, abs(_safe_mean(active)) * 10.0)

    # Match trusted-reference moment conventions while preserving deterministic
    # finite fallback for degenerate/non-finite outputs.
    skew = 0.0
    kurtosis = 0.0
    n = len(strat)
    if vol > 1e-12 and n > 2:
        centered_raw = [x - avg for x in strat]
        m2 = _safe_mean([x * x for x in centered_raw])
        if m2 > 0.0:
            m3 = _safe_mean([x ** 3 for x in centered_raw])
            g1 = m3 / (m2 ** 1.5)
            skew_candidate = math.sqrt(n * (n - 1)) / (n - 2) * g1
            skew = skew_candidate if math.isfinite(skew_candidate) else 0.0
    if vol > 1e-12 and n > 3:
        centered_raw = [x - avg for x in strat]
        m2 = _safe_mean([x * x for x in centered_raw])
        if m2 > 0.0:
            m4 = _safe_mean([x ** 4 for x in centered_raw])
            g2 = (m4 / (m2 * m2)) - 3.0
            g2_unbiased = ((n - 1) / ((n - 2) * (n - 3))) * ((n + 1) * g2 + 6.0)
            kurtosis_candidate = g2_unbiased + 3.0
            kurtosis = kurtosis_candidate if math.isfinite(kurtosis_candidate) else 0.0

    metrics = PerformanceMetrics(
        cagr=cagr,
        alpha=alpha,
        beta=beta,
        sharpe=sharpe,
        sortino=sortino,
        information_ratio=info_ratio,
        max_drawdown=max_dd,
        recovery_time_days=recovery,
        win_rate=hit_rate,
        hit_rate=hit_rate,
        turnover=turnover,
        volatility=vol * math.sqrt(annualization),
        skew=skew,
        kurtosis=kurtosis,
    )
    return {
        "experiment_id": experiment_id,
        "strategy_returns": tuple(strat),
        "benchmark_returns": tuple(bench),
        "metrics": metrics,
    }
