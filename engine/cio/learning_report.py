from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .calibration import CalibrationResult
from .performance_metrics import PerformanceMetrics
from .recommendation_analysis import RecommendationAnalysis


DEFAULT_REPORT_PATH = Path("artifacts") / "cio" / "performance_report.md"


@dataclass(frozen=True)
class PerformanceReport:
    generated_at: str
    metrics: PerformanceMetrics
    calibration: CalibrationResult
    analysis: RecommendationAnalysis
    report_path: str
    markdown: str
    source_summary: tuple[tuple[str, int], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_summary"] = list(self.source_summary)
        return payload


def _pct(value: float) -> str:
    return f"{value:.1%}"


def _num(value: float) -> str:
    return f"{value:.2f}"


def _render_group_table(title: str, rows) -> list[str]:
    lines = [f"### {title}", "", "| Label | Count | Avg Return | Benchmark Alpha | Win Rate | Avg Hold (days) |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in rows:
        lines.append(
            f"| {row.label} | {row.count} | {_pct(row.average_return)} | {_pct(row.benchmark_alpha)} | {_pct(row.win_rate)} | {_num(row.average_holding_period)} |"
        )
    lines.append("")
    return lines


def render_learning_report(report: PerformanceReport) -> str:
    metrics = report.metrics
    lines: list[str] = [
        f"# CIO Performance Lab Report - {report.generated_at}",
        "",
        "## Executive Summary",
        f"Closed recommendations: {metrics.closed_recommendation_count}",
        f"Overall win rate: {_pct(metrics.overall_win_rate)}",
        f"Directional accuracy: {_pct(metrics.directional_accuracy)}",
        f"Benchmark alpha: {_pct(metrics.benchmark_alpha)}",
        f"Confidence calibration score: {_num(metrics.confidence_calibration)}",
        "",
        "## Recommendation Accuracy",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Recommendation precision | {_pct(metrics.recommendation_precision)} |",
        f"| Recommendation recall | {_pct(metrics.recommendation_recall)} |",
        f"| Average return | {_pct(metrics.average_return)} |",
        f"| Median return | {_pct(metrics.median_return)} |",
        f"| Average holding period | {_num(metrics.average_holding_period)} days |",
        f"| Portfolio alpha | {_pct(metrics.portfolio_alpha)} |",
        f"| Buy accuracy | {_pct(metrics.buy_accuracy)} |",
        f"| Trim accuracy | {_pct(metrics.trim_accuracy)} |",
        f"| Cash timing accuracy | {_pct(metrics.cash_timing_accuracy)} |",
        f"| Thesis prediction accuracy | {_pct(metrics.thesis_prediction_accuracy)} |",
        f"| Replacement accuracy | {_pct(metrics.replacement_accuracy)} |",
        "",
        "## Confidence Calibration",
        "| Bucket | Count | Avg Return | Benchmark Alpha | Win Rate | Calibration Error |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for bucket in report.calibration.buckets:
        lines.append(
            f"| {bucket.label} | {bucket.count} | {_pct(bucket.average_return)} | {_pct(bucket.benchmark_alpha)} | {_pct(bucket.win_rate)} | {_num(bucket.calibration_error)} |"
        )

    lines.extend([
        "",
        "## Alpha Attribution",
        *(_render_group_table("Best Performing Recommendation Types", report.analysis.best_recommendation_types)),
        *(_render_group_table("Worst Performing Recommendation Types", report.analysis.worst_recommendation_types)),
        *(_render_group_table("Best Sectors", report.analysis.best_sectors)),
        *(_render_group_table("Worst Sectors", report.analysis.worst_sectors)),
        "## Failure Analysis",
    ])
    if report.analysis.largest_mistakes:
        for item in report.analysis.largest_mistakes:
            lines.append(
                f"- {item.symbol} {item.action_type} | confidence {_pct(item.confidence)} | benchmark alpha {_pct(item.benchmark_alpha)} | {item.recommendation_text or item.decision_id}"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Success Analysis"])
    if report.analysis.largest_successes:
        for item in report.analysis.largest_successes:
            lines.append(
                f"- {item.symbol} {item.action_type} | confidence {_pct(item.confidence)} | benchmark alpha {_pct(item.benchmark_alpha)} | {item.recommendation_text or item.decision_id}"
            )
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Suggested Areas for Improvement",
    ])
    if report.analysis.recurring_failure_patterns:
        for pattern in report.analysis.recurring_failure_patterns:
            lines.append(f"- {pattern}")
    else:
        lines.append("- No recurring failure pattern detected.")

    lines.extend([
        "",
        "## Open Questions",
        "- Which recommendation types should be split further by market regime or conviction band?",
        "- Do the weakest sectors remain weak after controlling for confidence and holding period?",
        "- Which thesis deltas should be tracked more explicitly in future briefs?",
    ])
    return "\n".join(lines) + "\n"


def write_learning_report(report: PerformanceReport, report_path: Path | None = None) -> Path:
    output_path = Path(report_path or report.report_path or DEFAULT_REPORT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.markdown, encoding="utf-8")
    return output_path
