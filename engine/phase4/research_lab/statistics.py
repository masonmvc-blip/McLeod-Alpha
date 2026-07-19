from __future__ import annotations

from hashlib import sha256
import math
import random
from statistics import NormalDist
from typing import Sequence

from .types import StatisticalTestResult


def _ensure_finite(values: Sequence[float], *, label: str) -> tuple[float, ...]:
    cleaned: list[float] = []
    for value in values:
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{label} contains non-finite value")
        cleaned.append(numeric)
    return tuple(cleaned)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _variance(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mu = _mean(values)
    return sum((x - mu) ** 2 for x in values) / (len(values) - 1)


def _stdev(values: Sequence[float]) -> float:
    return math.sqrt(max(0.0, _variance(values)))


def t_test_independent(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    if len(a) < 2 or len(b) < 2:
        return 0.0, 1.0
    mu_a = _mean(a)
    mu_b = _mean(b)
    var_a = _variance(a)
    var_b = _variance(b)
    denom = math.sqrt((var_a / len(a)) + (var_b / len(b)))
    if denom <= 0:
        return 0.0, 1.0
    t_stat = (mu_a - mu_b) / denom
    p = 2.0 * (1.0 - NormalDist().cdf(abs(t_stat)))
    return t_stat, max(0.0, min(1.0, p))


def mann_whitney_u(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    if not a or not b:
        return 0.0, 1.0

    combined = [(float(x), 0) for x in a] + [(float(x), 1) for x in b]
    combined.sort(key=lambda row: row[0])

    # Assign average ranks across ties to match trusted statistical conventions.
    ranks = [0.0 for _ in combined]
    tie_counts: list[int] = []
    i = 0
    while i < len(combined):
        j = i
        while j + 1 < len(combined) and combined[j + 1][0] == combined[i][0]:
            j += 1
        rank_avg = (i + 1 + j + 1) / 2.0
        tie_size = j - i + 1
        tie_counts.append(tie_size)
        for k in range(i, j + 1):
            ranks[k] = rank_avg
        i = j + 1

    rank_sum_a = 0.0
    for rank, (_, grp) in zip(ranks, combined):
        if grp == 0:
            rank_sum_a += rank

    n1 = len(a)
    n2 = len(b)
    u1 = rank_sum_a - (n1 * (n1 + 1) / 2.0)
    u2 = n1 * n2 - u1

    mean_u = n1 * n2 / 2.0
    n = n1 + n2
    tie_term = sum((t ** 3) - t for t in tie_counts if t > 1)
    tie_correction = tie_term / (n * (n - 1)) if n > 1 else 0.0
    variance_u = (n1 * n2 / 12.0) * ((n + 1.0) - tie_correction)
    if variance_u <= 0.0:
        return float(u1), 1.0

    # Two-sided asymptotic p-value with continuity correction.
    u = min(u1, u2)
    z = (abs(u - mean_u) - 0.5) / math.sqrt(variance_u)
    p = 2.0 * (1.0 - NormalDist().cdf(abs(z)))
    return u1, max(0.0, min(1.0, p))


def bootstrap_confidence_interval(
    values: Sequence[float],
    *,
    iterations: int = 1000,
    confidence: float = 0.95,
    seed_material: str = "bootstrap",
) -> tuple[float, float]:
    if iterations <= 0:
        raise ValueError("iterations must be > 0")
    if not (0.0 < confidence < 1.0):
        raise ValueError("confidence must be in (0, 1)")
    values = _ensure_finite(values, label="bootstrap values")
    if not values:
        raise ValueError("bootstrap values cannot be empty")
    seed = int(sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    means: list[float] = []
    n = len(values)
    for _ in range(max(100, iterations)):
        sample = [values[rng.randrange(0, n)] for _ in range(n)]
        means.append(_mean(sample))
    means.sort()
    alpha = 1.0 - confidence
    lo_idx = int(alpha / 2.0 * (len(means) - 1))
    hi_idx = int((1.0 - alpha / 2.0) * (len(means) - 1))
    return float(means[lo_idx]), float(means[hi_idx])


def monte_carlo_p_value(
    strategy_returns: Sequence[float],
    benchmark_returns: Sequence[float],
    *,
    iterations: int = 1000,
    seed_material: str = "monte_carlo",
) -> float:
    if iterations <= 0:
        raise ValueError("iterations must be > 0")
    strategy_returns = _ensure_finite(strategy_returns, label="strategy_returns")
    benchmark_returns = _ensure_finite(benchmark_returns, label="benchmark_returns")
    if not strategy_returns or not benchmark_returns:
        raise ValueError("strategy_returns and benchmark_returns cannot be empty")
    if len(strategy_returns) != len(benchmark_returns):
        raise ValueError("strategy_returns and benchmark_returns must have equal lengths")
    observed = _mean(strategy_returns) - _mean(benchmark_returns)
    seed = int(sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    pool = [float(x) for x in strategy_returns] + [float(x) for x in benchmark_returns]
    greater_or_equal = 0
    for _ in range(max(100, iterations)):
        rng.shuffle(pool)
        split = len(strategy_returns)
        diff = _mean(pool[:split]) - _mean(pool[split: split + len(benchmark_returns)])
        if abs(diff) >= abs(observed):
            greater_or_equal += 1
    return greater_or_equal / max(1, iterations)


def cohen_d(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return 0.0
    var_a = _variance(a)
    var_b = _variance(b)
    pooled = math.sqrt(max(1e-12, ((len(a) - 1) * var_a + (len(b) - 1) * var_b) / (len(a) + len(b) - 2)))
    return (_mean(a) - _mean(b)) / pooled


def false_discovery_adjustment(p_value: float, num_hypotheses: int) -> float:
    if num_hypotheses <= 0:
        return p_value
    return max(0.0, min(1.0, p_value * num_hypotheses))


def evaluate_statistical_tests(
    *,
    strategy_returns: Sequence[float],
    benchmark_returns: Sequence[float],
    num_hypotheses: int,
) -> StatisticalTestResult:
    strategy_returns = _ensure_finite(strategy_returns, label="strategy_returns")
    benchmark_returns = _ensure_finite(benchmark_returns, label="benchmark_returns")
    if len(strategy_returns) < 2 or len(benchmark_returns) < 2:
        raise ValueError("need at least 2 observations in each return series")
    if len(strategy_returns) != len(benchmark_returns):
        raise ValueError("strategy_returns and benchmark_returns must have equal lengths")
    if num_hypotheses <= 0:
        raise ValueError("num_hypotheses must be > 0")

    t_stat, t_p = t_test_independent(strategy_returns, benchmark_returns)
    u_stat, u_p = mann_whitney_u(strategy_returns, benchmark_returns)
    ci_low, ci_high = bootstrap_confidence_interval(
        [x - y for x, y in zip(strategy_returns, benchmark_returns)],
        seed_material="bootstrap|strategy_vs_benchmark",
    )
    mc_p = monte_carlo_p_value(
        strategy_returns,
        benchmark_returns,
        seed_material="mc|strategy_vs_benchmark",
    )
    d = cohen_d(strategy_returns, benchmark_returns)
    adjusted = false_discovery_adjustment(min(t_p, u_p, mc_p), num_hypotheses)
    oos_passed = bool(adjusted < 0.1 and ci_high >= ci_low)
    return StatisticalTestResult(
        t_statistic=t_stat,
        t_p_value=t_p,
        mann_whitney_u=u_stat,
        mann_whitney_p_value=u_p,
        effect_size=d,
        bootstrap_ci_low=ci_low,
        bootstrap_ci_high=ci_high,
        monte_carlo_p_value=mc_p,
        false_discovery_adjusted_p=adjusted,
        out_of_sample_passed=oos_passed,
    )
