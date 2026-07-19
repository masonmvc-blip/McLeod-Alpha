from __future__ import annotations

from typing import Sequence

from .types import ExperimentResult, FeatureImportanceScore, RecommendedWeightAdjustment


def _line(key: str, value: str) -> str:
    return f"- {key}: {value}"


def _provenance_value(result: ExperimentResult, key: str, default: str = "UNKNOWN") -> str:
    value = str((result.provenance or {}).get(key) or "").strip()
    return value or default


def _disclosure_lines(result: ExperimentResult, *, synthetic_only: bool) -> list[str]:
    return [
        _line("dataset_identity", _provenance_value(result, "dataset_id")),
        _line("dataset_version", _provenance_value(result, "dataset_version", "1.0")),
        _line("date_range", _provenance_value(result, "date_range")),
        _line("universe", _provenance_value(result, "universe")),
        _line("survivorship_policy", _provenance_value(result, "survivorship_policy")),
        _line("publication_lag_policy", _provenance_value(result, "publication_lag_policy")),
        _line("transaction_assumptions", _provenance_value(result, "transaction_assumptions")),
        _line("benchmark", _provenance_value(result, "benchmark")),
        _line("sample_size", _provenance_value(result, "sample_size")),
        _line("validation_method", _provenance_value(result, "validation_method")),
        _line("multiple_testing_correction", _provenance_value(result, "multiple_testing_correction", "Benjamini-Hochberg style scalar adjustment")),
        _line("reproducibility_seed", _provenance_value(result, "deterministic_seed")),
        _line("failed_checks", ", ".join(result.overfitting_check.reasons) if result.overfitting_check.reasons else "None"),
        _line("warnings", _provenance_value(result, "warnings", "None")),
        _line("limitations", _provenance_value(result, "limitations", "Synthetic validation fixture")),
        _line("artifact_hashes", _provenance_value(result, "artifact_hashes", "not_recorded")),
        _line("data_classification", "SYNTHETIC_VALIDATION_ONLY" if synthetic_only else _provenance_value(result, "data_classification")),
    ]


def render_research_lab_summary(result: ExperimentResult, *, synthetic_only: bool = False) -> str:
    lines = [
        "# research_lab_summary_v1",
        "",
        "SYNTHETIC_VALIDATION_ONLY" if synthetic_only else "HISTORICAL_RESEARCH_CONTEXT",
        "",
        _line("experiment_id", result.experiment_id),
        _line("status", result.status.value),
        _line("cagr", f"{result.metrics.cagr:.6f}"),
        _line("alpha", f"{result.metrics.alpha:.6f}"),
        _line("sharpe", f"{result.metrics.sharpe:.6f}"),
        _line("max_drawdown", f"{result.metrics.max_drawdown:.6f}"),
        _line("overfitting_passed", str(result.overfitting_check.passed)),
    ]
    lines.extend(["", "## Disclosures", *(_disclosure_lines(result, synthetic_only=synthetic_only))])
    if synthetic_only:
        lines.extend(
            [
                "",
                "No historical alpha conclusion.",
                "No production-weight implication.",
                "No activation implication.",
                "No live-trading implication.",
            ]
        )
    return "\n".join(lines) + "\n"


def render_experiment_report(result: ExperimentResult, *, synthetic_only: bool = False) -> str:
    lines = [
        "# experiment_report_v1",
        "",
        "SYNTHETIC_VALIDATION_ONLY" if synthetic_only else "HISTORICAL_RESEARCH_CONTEXT",
        "",
        _line("experiment_id", result.experiment_id),
        _line("win_rate", f"{result.metrics.win_rate:.6f}"),
        _line("information_ratio", f"{result.metrics.information_ratio:.6f}"),
        _line("sortino", f"{result.metrics.sortino:.6f}"),
        _line("volatility", f"{result.metrics.volatility:.6f}"),
        _line("t_statistic", f"{result.statistical_tests.t_statistic:.6f}"),
        _line("t_p_value", f"{result.statistical_tests.t_p_value:.6f}"),
        _line("mann_whitney_u", f"{result.statistical_tests.mann_whitney_u:.6f}"),
        _line("mann_whitney_p_value", f"{result.statistical_tests.mann_whitney_p_value:.6f}"),
        _line("bootstrap_ci", f"[{result.statistical_tests.bootstrap_ci_low:.6f}, {result.statistical_tests.bootstrap_ci_high:.6f}]"),
        _line("monte_carlo_p_value", f"{result.statistical_tests.monte_carlo_p_value:.6f}"),
        _line("false_discovery_adjusted_p", f"{result.statistical_tests.false_discovery_adjusted_p:.6f}"),
        _line("in_sample_results", _provenance_value(result, "in_sample_results", "see metrics above")),
        _line("out_of_sample_results", "passed" if result.statistical_tests.out_of_sample_passed else "failed"),
    ]
    lines.extend(["", "## Disclosures", *(_disclosure_lines(result, synthetic_only=synthetic_only))])
    if synthetic_only:
        lines.extend(
            [
                "",
                "No historical alpha conclusion.",
                "No production-weight implication.",
                "No activation implication.",
                "No live-trading implication.",
            ]
        )
    return "\n".join(lines) + "\n"


def render_factor_rankings(rankings: Sequence[FeatureImportanceScore]) -> str:
    lines = ["# factor_rankings_v1", "", "|rank|factor|score|stability|persistence|redundancy|", "|---:|---|---:|---:|---:|---:|"]
    for idx, row in enumerate(rankings, start=1):
        lines.append(
            f"|{idx}|{row.factor}|{row.composite_score:.6f}|{row.stability:.6f}|{row.persistence:.6f}|{row.redundancy:.6f}|"
        )
    return "\n".join(lines) + "\n"


def render_model_improvement_recommendations(
    adjustments: Sequence[RecommendedWeightAdjustment],
    *,
    synthetic_only: bool = False,
) -> str:
    lines = [
        "# model_improvement_recommendations_v1",
        "",
        "SYNTHETIC_VALIDATION_ONLY" if synthetic_only else "HISTORICAL_RESEARCH_CONTEXT",
        "",
        "All recommendations require human approval.",
    ]
    for adj in adjustments:
        lines.extend(
            [
                "",
                f"## {adj.factor}",
                _line("current_weight", f"{adj.current_weight:.6f}"),
                _line("recommended_weight", f"{adj.recommended_weight:.6f}"),
                _line("confidence", f"{adj.confidence:.6f}"),
                _line("expected_improvement", f"{adj.expected_improvement:.6f}"),
                _line("statistical_significance", f"{adj.statistical_significance:.6f}"),
                _line("evidence", adj.evidence),
                _line("risks", ", ".join(adj.risks)),
                _line("supporting_experiments", ", ".join(adj.supporting_experiments)),
                _line("human_approval_required", str(adj.human_approval_required)),
            ]
        )
    if synthetic_only:
        lines.extend(
            [
                "",
                "No historical alpha conclusion.",
                "No production-weight implication.",
                "No activation implication.",
                "No live-trading implication.",
            ]
        )
    return "\n".join(lines) + "\n"
