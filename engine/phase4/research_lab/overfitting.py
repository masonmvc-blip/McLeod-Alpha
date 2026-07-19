from __future__ import annotations

from typing import Sequence

from .types import OverfittingCheck


def detect_overfitting(
    *,
    strategy_returns: Sequence[float],
    benchmark_returns: Sequence[float],
    sample_size: int,
    num_trials: int,
    look_ahead_prevention: bool,
    survivorship_policy: str,
    data_quality_score: float,
) -> OverfittingCheck:
    reasons: list[str] = []
    look_ahead_bias = not look_ahead_prevention
    survivorship_bias = survivorship_policy != "INCLUDE_DELISTED"
    data_leakage = data_quality_score < 0.7
    p_hacking = num_trials > max(20, sample_size // 2)
    multiple_comparisons = num_trials > 10

    mean_strategy = sum(strategy_returns) / max(1, len(strategy_returns))
    mean_benchmark = sum(benchmark_returns) / max(1, len(benchmark_returns))
    unstable_parameters = abs(mean_strategy - mean_benchmark) > 0.08 and sample_size < 250
    insufficient_sample_size = sample_size < 120
    excessive_optimization = num_trials > sample_size

    checks = {
        "look_ahead_bias": look_ahead_bias,
        "survivorship_bias": survivorship_bias,
        "data_leakage": data_leakage,
        "p_hacking": p_hacking,
        "multiple_comparisons": multiple_comparisons,
        "unstable_parameters": unstable_parameters,
        "insufficient_sample_size": insufficient_sample_size,
        "excessive_optimization": excessive_optimization,
    }
    for name, failed in checks.items():
        if failed:
            reasons.append(name.upper())

    passed = not any(checks.values())
    return OverfittingCheck(
        look_ahead_bias=look_ahead_bias,
        survivorship_bias=survivorship_bias,
        data_leakage=data_leakage,
        p_hacking=p_hacking,
        multiple_comparisons=multiple_comparisons,
        unstable_parameters=unstable_parameters,
        insufficient_sample_size=insufficient_sample_size,
        excessive_optimization=excessive_optimization,
        passed=passed,
        reasons=tuple(sorted(reasons)),
    )
