from __future__ import annotations

from typing import Mapping, Sequence

from .types import ExperimentSpec, ResearchLabValidationResult


def validate_experiment_inputs(
    *,
    spec: ExperimentSpec,
    factor_returns: Mapping[str, Sequence[float]],
    benchmark_returns: Sequence[float],
) -> ResearchLabValidationResult:
    deterministic_seed = str((spec.provenance or {}).get("deterministic_seed") or "").strip()
    checks: dict[str, bool] = {
        "look_ahead_prevention": bool(spec.look_ahead_prevention),
        "survivorship_bias_control": spec.survivorship_policy.value == "INCLUDE_DELISTED",
        "data_quality": spec.data_quality_score >= 0.7,
        "required_factor_data": all(name in factor_returns for name in spec.factors),
        "benchmark_present": len(benchmark_returns) > 0,
        "sample_size": len(benchmark_returns) >= spec.dataset.required_sample_size,
        "deterministic_seed_present": bool(deterministic_seed),
    }
    failures = [k for k, passed in checks.items() if not passed]
    result = ResearchLabValidationResult(
        passed=not failures,
        checks=dict(sorted(checks.items())),
        failures=tuple(sorted(failures)),
    )
    if not result.passed:
        raise ValueError(f"Experiment validation failed: {', '.join(result.failures)}")
    return result


def validate_bias_leakage_controls(*, contamination_flags: Mapping[str, bool]) -> ResearchLabValidationResult:
    required_flags = (
        "future_fundamental_data",
        "future_prices",
        "revised_macro_data",
        "post_period_index_membership",
        "survivor_only_universe",
        "delisted_omission",
        "overlapping_train_test",
        "target_leakage_derived_features",
        "timestamp_misalignment",
        "filing_date_period_end_confusion",
        "publication_lag_violation",
        "corporate_action_hindsight",
        "benchmark_look_ahead",
        "universe_selection_look_ahead",
    )
    checks: dict[str, bool] = {}
    for flag in required_flags:
        checks[flag] = not bool(contamination_flags.get(flag, False))

    failures = [k for k, passed in checks.items() if not passed]
    result = ResearchLabValidationResult(
        passed=not failures,
        checks=dict(sorted(checks.items())),
        failures=tuple(sorted(failures)),
    )
    if not result.passed:
        raise ValueError("Bias/leakage controls failed: " + ", ".join(result.failures))
    return result
