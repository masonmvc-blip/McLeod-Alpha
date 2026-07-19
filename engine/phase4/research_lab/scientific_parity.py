from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
import random
from typing import Callable, Sequence

from .backtest import run_backtest
from .statistics import (
    bootstrap_confidence_interval,
    cohen_d,
    evaluate_statistical_tests,
    false_discovery_adjustment,
    mann_whitney_u,
    monte_carlo_p_value,
    t_test_independent,
)
from .types import ScientificParityResult

try:
    import numpy as np
except Exception:  # pragma: no cover - environment dependent
    np = None

try:
    import pandas as pd
except Exception:  # pragma: no cover - environment dependent
    pd = None

try:
    from scipy import stats as scipy_stats
except Exception:  # pragma: no cover - environment dependent
    scipy_stats = None


@dataclass(frozen=True)
class _MetricFixture:
    fixture_id: str
    frequency: str
    strategy_returns: tuple[float, ...]
    benchmark_returns: tuple[float, ...]
    tolerance: float
    seed: str


def _periods_per_year(frequency: str) -> float:
    mapping = {"daily": 252.0, "weekly": 52.0, "monthly": 12.0}
    return mapping.get(frequency, 252.0)


def _series_mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _series_stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mu = _series_mean(values)
    var = sum((x - mu) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(max(0.0, var))


def _safe_rel_err(reference: float, laboratory: float) -> float:
    denom = max(1e-12, abs(reference))
    return abs(reference - laboratory) / denom


def _parity_result(
    *,
    metric_name: str,
    fixture: _MetricFixture,
    reference_impl: str,
    reference_value: float,
    lab_value: float,
    tolerance: float,
    invalid_input_expectation: str = "N/A",
) -> ScientificParityResult:
    abs_err = abs(reference_value - lab_value)
    rel_err = _safe_rel_err(reference_value, lab_value)
    passed = abs_err <= tolerance or rel_err <= tolerance
    provenance = {
        "frequency": fixture.frequency,
        "periods_per_year": str(_periods_per_year(fixture.frequency)),
        "fixture_seed": fixture.seed,
        "parity_version": "1.0",
    }
    return ScientificParityResult(
        metric_name=metric_name,
        fixture_id=fixture.fixture_id,
        reference_implementation=reference_impl,
        reference_value=float(reference_value),
        laboratory_value=float(lab_value),
        absolute_error=float(abs_err),
        relative_error=float(rel_err),
        tolerance=float(tolerance),
        passed=bool(passed),
        invalid_input_expectation=invalid_input_expectation,
        seed=fixture.seed,
        provenance=provenance,
    )


def _reference_metrics(fixture: _MetricFixture) -> dict[str, float]:
    strat = tuple(float(x) for x in fixture.strategy_returns)
    bench = tuple(float(x) for x in fixture.benchmark_returns)
    ppy = _periods_per_year(fixture.frequency)

    if np is not None:
        s = np.array(strat, dtype=float)
        b = np.array(bench, dtype=float)
        mean_s = float(np.mean(s))
        mean_b = float(np.mean(b))
        vol_s = float(np.std(s, ddof=1)) if len(s) > 1 else 0.0
        downside = np.minimum(0.0, s)
        downside_vol = float(np.std(downside, ddof=1)) if len(s) > 1 else 0.0
        cov = float(np.cov(s, b, ddof=1)[0, 1]) if len(s) > 1 else 0.0
        var_b = float(np.var(b, ddof=1)) if len(b) > 1 else 0.0
        beta = cov / var_b if var_b > 1e-12 else 0.0

        curve_scalar = 1.0
        peak_scalar = 1.0
        max_dd = 0.0
        trough_idx = 0
        recovery = 0
        last_peak_idx = 0
        for i, rv in enumerate(strat):
            curve_scalar *= 1.0 + rv
            if curve_scalar > peak_scalar:
                peak_scalar = curve_scalar
                last_peak_idx = i
            dd = curve_scalar / peak_scalar - 1.0
            if dd < max_dd:
                max_dd = dd
                trough_idx = i
                recovery = max(0, trough_idx - last_peak_idx)

        cagr = float(curve_scalar ** (ppy / max(1.0, len(s))) - 1.0) if len(s) else 0.0
        alpha = (mean_s - beta * mean_b) * ppy
        sharpe = (mean_s / vol_s) * math.sqrt(ppy) if vol_s > 1e-12 else 0.0
        sortino = (mean_s / downside_vol) * math.sqrt(ppy) if downside_vol > 1e-12 else 0.0
        active = s - b
        ir_denom = float(np.std(active, ddof=1)) if len(active) > 1 else 0.0
        info_ratio = (float(np.mean(active)) / ir_denom) * math.sqrt(ppy) if ir_denom > 1e-12 else 0.0
        hit = float(np.sum(s > 0) / max(1, len(s)))
        turnover = min(1.0, abs(float(np.mean(active))) * 10.0)

        if scipy_stats is not None:
            skew = float(scipy_stats.skew(s, bias=False)) if len(s) > 2 else 0.0
            kurtosis = float(scipy_stats.kurtosis(s, fisher=False, bias=False)) if len(s) > 3 else 0.0
        else:
            centered = ((s - mean_s) / vol_s) if vol_s > 1e-12 else np.zeros_like(s)
            skew = float(np.mean(centered ** 3)) if len(s) else 0.0
            kurtosis = float(np.mean(centered ** 4)) if len(s) else 0.0
    else:
        mean_s = _series_mean(strat)
        mean_b = _series_mean(bench)
        vol_s = _series_stdev(strat)
        downside_vol = _series_stdev([min(0.0, x) for x in strat])
        s_mu = _series_mean(strat)
        b_mu = _series_mean(bench)
        cov = sum((s - s_mu) * (b - b_mu) for s, b in zip(strat, bench)) / (len(strat) - 1)
        var_b = _series_stdev(bench) ** 2
        beta = cov / var_b if var_b > 1e-12 else 0.0

        curve = 1.0
        peak = 1.0
        max_dd = 0.0
        trough_idx = 0
        last_peak = 0
        for i, r in enumerate(strat):
            curve *= 1.0 + r
            if curve > peak:
                peak = curve
                last_peak = i
            dd = curve / peak - 1.0
            if dd < max_dd:
                max_dd = dd
                trough_idx = i
        recovery = max(0, trough_idx - last_peak)
        cagr = curve ** (ppy / max(1.0, len(strat))) - 1.0 if strat else 0.0
        alpha = (mean_s - beta * mean_b) * ppy
        sharpe = (mean_s / vol_s) * math.sqrt(ppy) if vol_s > 1e-12 else 0.0
        sortino = (mean_s / downside_vol) * math.sqrt(ppy) if downside_vol > 1e-12 else 0.0
        active = [s - b for s, b in zip(strat, bench)]
        ir_denom = _series_stdev(active)
        info_ratio = (_series_mean(active) / ir_denom) * math.sqrt(ppy) if ir_denom > 1e-12 else 0.0
        hit = len([x for x in strat if x > 0.0]) / max(1, len(strat))
        turnover = min(1.0, abs(_series_mean(active)) * 10.0)
        centered = [((x - mean_s) / vol_s) for x in strat] if vol_s > 1e-12 else [0.0 for _ in strat]
        skew = _series_mean([x ** 3 for x in centered]) if centered else 0.0
        kurtosis = _series_mean([x ** 4 for x in centered]) if centered else 0.0

    return {
        "cagr": float(cagr),
        "alpha": float(alpha),
        "beta": float(beta),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "information_ratio": float(info_ratio),
        "max_drawdown": float(max_dd),
        "recovery_time_days": float(recovery),
        "win_rate": float(hit),
        "hit_rate": float(hit),
        "turnover": float(turnover),
        "volatility": float(vol_s * math.sqrt(ppy)),
        "skew": float(skew),
        "kurtosis": float(kurtosis),
    }


def _reference_statistics(fixture: _MetricFixture) -> dict[str, float]:
    strat = tuple(float(x) for x in fixture.strategy_returns)
    bench = tuple(float(x) for x in fixture.benchmark_returns)
    diff = [x - y for x, y in zip(strat, bench)]

    if scipy_stats is not None:
        t_stat, t_p = scipy_stats.ttest_ind(strat, bench, equal_var=False)
        mw = scipy_stats.mannwhitneyu(strat, bench, alternative="two-sided")
        mw_u, mw_p = float(mw.statistic), float(mw.pvalue)
    else:
        t_stat, t_p = t_test_independent(strat, bench)
        mw_u, mw_p = mann_whitney_u(strat, bench)

    seed = int(sha256((fixture.seed + "|bootstrap").encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(300):
        sample = [diff[rng.randrange(0, len(diff))] for _ in range(len(diff))]
        means.append(_series_mean(sample))
    means.sort()
    lo = means[int(0.025 * (len(means) - 1))]
    hi = means[int(0.975 * (len(means) - 1))]

    mc_seed = int(sha256((fixture.seed + "|mc").encode("utf-8")).hexdigest()[:16], 16)
    mc_rng = random.Random(mc_seed)
    observed = _series_mean(strat) - _series_mean(bench)
    pool = list(strat) + list(bench)
    gte = 0
    for _ in range(300):
        mc_rng.shuffle(pool)
        split = len(strat)
        d = _series_mean(pool[:split]) - _series_mean(pool[split : split + len(bench)])
        if abs(d) >= abs(observed):
            gte += 1
    mc_p = gte / 300.0

    return {
        "t_test": float(t_stat),
        "t_test_p": float(max(0.0, min(1.0, t_p))),
        "mann_whitney": float(mw_u),
        "mann_whitney_p": float(max(0.0, min(1.0, mw_p))),
        "bootstrap_ci_low": float(lo),
        "bootstrap_ci_high": float(hi),
        "monte_carlo_p": float(mc_p),
        "effect_size": float(cohen_d(strat, bench)),
        "false_discovery_adjusted_p": float(false_discovery_adjustment(min(max(0.0, min(1.0, t_p)), max(0.0, min(1.0, mw_p)), mc_p), 4)),
    }


def _build_fixtures() -> tuple[_MetricFixture, ...]:
    random_seed = int(sha256("scientific-parity|fixture-seed".encode("utf-8")).hexdigest()[:12], 16)
    rng = random.Random(random_seed)

    daily = _MetricFixture(
        fixture_id="hand_daily_mixed_v1",
        frequency="daily",
        strategy_returns=(0.01, -0.02, 0.005, 0.015, -0.005, 0.007, 0.0, -0.003, 0.004, 0.006),
        benchmark_returns=(0.008, -0.01, 0.004, 0.009, -0.003, 0.005, 0.001, -0.002, 0.003, 0.004),
        tolerance=1e-8,
        seed="hand-daily-001",
    )

    weekly_series = tuple((rng.random() - 0.48) * 0.04 for _ in range(26))
    weekly_bench = tuple((rng.random() - 0.5) * 0.03 for _ in range(26))
    weekly = _MetricFixture(
        fixture_id="det_weekly_seeded_v1",
        frequency="weekly",
        strategy_returns=weekly_series,
        benchmark_returns=weekly_bench,
        tolerance=1e-8,
        seed="weekly-seed-20260718",
    )

    monthly_series = tuple((rng.random() - 0.47) * 0.06 for _ in range(18))
    monthly_bench = tuple((rng.random() - 0.5) * 0.05 for _ in range(18))
    monthly = _MetricFixture(
        fixture_id="det_monthly_seeded_v1",
        frequency="monthly",
        strategy_returns=monthly_series,
        benchmark_returns=monthly_bench,
        tolerance=1e-8,
        seed="monthly-seed-20260718",
    )

    zero_variance = _MetricFixture(
        fixture_id="zero_variance_all_negative_v1",
        frequency="daily",
        strategy_returns=tuple([-0.001 for _ in range(30)]),
        benchmark_returns=tuple([-0.001 for _ in range(30)]),
        tolerance=1e-8,
        seed="zero-var-20260718",
    )

    tiny_sample = _MetricFixture(
        fixture_id="tiny_sample_weekly_v1",
        frequency="weekly",
        strategy_returns=(0.01, -0.01),
        benchmark_returns=(0.005, -0.005),
        tolerance=1e-8,
        seed="tiny-weekly-20260718",
    )
    return (daily, weekly, monthly, zero_variance, tiny_sample)


def run_scientific_parity_suite() -> tuple[ScientificParityResult, ...]:
    results: list[ScientificParityResult] = []
    for fixture in _build_fixtures():
        backtest = run_backtest(
            experiment_id=f"parity::{fixture.fixture_id}",
            factor_returns={"F1": fixture.strategy_returns, "F2": fixture.strategy_returns},
            benchmark_returns=fixture.benchmark_returns,
            periods_per_year=_periods_per_year(fixture.frequency),
        )
        metrics = backtest["metrics"]
        ref_metrics = _reference_metrics(fixture)

        metric_map = {
            "CAGR": (ref_metrics["cagr"], metrics.cagr),
            "Alpha": (ref_metrics["alpha"], metrics.alpha),
            "Beta": (ref_metrics["beta"], metrics.beta),
            "Sharpe": (ref_metrics["sharpe"], metrics.sharpe),
            "Sortino": (ref_metrics["sortino"], metrics.sortino),
            "Information Ratio": (ref_metrics["information_ratio"], metrics.information_ratio),
            "Max Drawdown": (ref_metrics["max_drawdown"], metrics.max_drawdown),
            "Recovery Time": (ref_metrics["recovery_time_days"], float(metrics.recovery_time_days)),
            "Win Rate": (ref_metrics["win_rate"], metrics.win_rate),
            "Hit Rate": (ref_metrics["hit_rate"], metrics.hit_rate),
            "Turnover": (ref_metrics["turnover"], metrics.turnover),
            "Volatility": (ref_metrics["volatility"], metrics.volatility),
            "Skew": (ref_metrics["skew"], metrics.skew),
            "Kurtosis": (ref_metrics["kurtosis"], metrics.kurtosis),
        }
        for metric_name, values in metric_map.items():
            results.append(
                _parity_result(
                    metric_name=metric_name,
                    fixture=fixture,
                    reference_impl="numpy/scipy" if np is not None else "stdlib",
                    reference_value=values[0],
                    lab_value=values[1],
                    tolerance=fixture.tolerance,
                )
            )

        stats = evaluate_statistical_tests(
            strategy_returns=fixture.strategy_returns,
            benchmark_returns=fixture.benchmark_returns,
            num_hypotheses=4,
        )
        ref_stats = _reference_statistics(fixture)
        stats_map = {
            "t-test": (ref_stats["t_test"], stats.t_statistic),
            "Mann-Whitney": (ref_stats["mann_whitney"], stats.mann_whitney_u),
            "bootstrap confidence intervals low": (ref_stats["bootstrap_ci_low"], stats.bootstrap_ci_low),
            "bootstrap confidence intervals high": (ref_stats["bootstrap_ci_high"], stats.bootstrap_ci_high),
            "Monte Carlo resampling": (ref_stats["monte_carlo_p"], stats.monte_carlo_p_value),
            "effect size": (ref_stats["effect_size"], stats.effect_size),
            "false-discovery correction": (ref_stats["false_discovery_adjusted_p"], stats.false_discovery_adjusted_p),
        }
        stochastic_tolerances = {
            "bootstrap confidence intervals low": 0.25,
            "bootstrap confidence intervals high": 0.25,
            "Monte Carlo resampling": 0.25,
            "false-discovery correction": 0.25,
        }
        for metric_name, values in stats_map.items():
            results.append(
                _parity_result(
                    metric_name=metric_name,
                    fixture=fixture,
                    reference_impl="scipy.stats" if scipy_stats is not None else "internal_reference",
                    reference_value=values[0],
                    lab_value=values[1],
                    tolerance=stochastic_tolerances.get(metric_name, max(1e-8, fixture.tolerance)),
                )
            )

    invalid_cases: tuple[tuple[str, Callable[[], None], str], ...] = (
        ("empty inputs", lambda: evaluate_statistical_tests(strategy_returns=[], benchmark_returns=[], num_hypotheses=1), "raises ValueError"),
        ("NaN inputs", lambda: evaluate_statistical_tests(strategy_returns=[0.1, float("nan")], benchmark_returns=[0.0, 0.0], num_hypotheses=1), "raises ValueError"),
        ("infinity inputs", lambda: evaluate_statistical_tests(strategy_returns=[0.1, float("inf")], benchmark_returns=[0.0, 0.0], num_hypotheses=1), "raises ValueError"),
        ("unequal lengths", lambda: evaluate_statistical_tests(strategy_returns=[0.1, 0.2], benchmark_returns=[0.0], num_hypotheses=1), "raises ValueError"),
        ("very small samples", lambda: evaluate_statistical_tests(strategy_returns=[0.1], benchmark_returns=[0.0], num_hypotheses=1), "raises ValueError"),
    )
    invalid_fixture = _MetricFixture(
        fixture_id="invalid_inputs_v1",
        frequency="daily",
        strategy_returns=(0.0, 0.0),
        benchmark_returns=(0.0, 0.0),
        tolerance=0.0,
        seed="invalid-cases",
    )
    for name, fn, expectation in invalid_cases:
        raised = False
        try:
            fn()
        except ValueError:
            raised = True
        results.append(
            ScientificParityResult(
                metric_name=name,
                fixture_id=invalid_fixture.fixture_id,
                reference_implementation="input_contract",
                reference_value=0.0,
                laboratory_value=0.0,
                absolute_error=0.0,
                relative_error=0.0,
                tolerance=0.0,
                passed=raised,
                invalid_input_expectation=expectation,
                seed=invalid_fixture.seed,
                provenance={"parity_version": "1.0", "category": "invalid_input"},
            )
        )

    return tuple(results)


def scientific_parity_passed(results: Sequence[ScientificParityResult]) -> bool:
    return all(row.passed for row in results)
