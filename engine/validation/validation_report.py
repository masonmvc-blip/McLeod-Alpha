from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .benchmark_analysis import BenchmarkAnalysisResult
from .calibration_analysis import CalibrationAnalysisResult
from .drift_detection import DriftDetectionResult
from .historical_replay import HistoricalReplayResult


DEFAULT_REPORT_PATH = Path("artifacts") / "validation" / "validation_report.md"


@dataclass(frozen=True)
class ValidationReport:
    generated_at: str
    replay_result: HistoricalReplayResult
    benchmark_result: BenchmarkAnalysisResult
    calibration_result: CalibrationAnalysisResult
    drift_result: DriftDetectionResult
    failure_cases: tuple[str, ...]
    success_cases: tuple[str, ...]
    recommended_improvements: tuple[str, ...]
    report_path: str
    markdown: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


def _pct(value: float) -> str:
    return f"{value:.2%}"


def _num(value: float) -> str:
    return f"{value:.4f}"


def render_validation_report(report: ValidationReport) -> str:
    lines: list[str] = [
        f"# Validation Lab Report - {report.generated_at}",
        "",
        "## Executive Summary",
        f"Replay points: {len(report.replay_result.points)}",
        f"Hit rate: {_pct(report.benchmark_result.hit_rate)}",
        f"Alpha vs SPY: {_pct(report.benchmark_result.alpha_vs_spy)}",
        f"Confidence accuracy: {_pct(report.calibration_result.confidence_accuracy)}",
        "",
        "## Historical Replay Results",
        "| Date | CIO Return | SPY Return | Equal Weight | Benchmark | Confidence |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for point in report.replay_result.points:
        lines.append(
            f"| {point.as_of_date} | {_pct(point.cio_return)} | {_pct(point.spy_return)} | {_pct(point.equal_weight_return)} | {_pct(point.benchmark_return)} | {_num(point.confidence_score)} |"
        )

    lines.extend([
        "",
        "## Benchmark Comparison",
        f"- Alpha vs SPY: {_pct(report.benchmark_result.alpha_vs_spy)}",
        f"- Alpha vs equal weight: {_pct(report.benchmark_result.alpha_vs_equal_weight)}",
        f"- Alpha vs benchmark portfolio: {_pct(report.benchmark_result.alpha_vs_benchmark_portfolio)}",
        f"- Sharpe: {_num(report.benchmark_result.sharpe)}",
        f"- Sortino: {_num(report.benchmark_result.sortino)}",
        f"- Max drawdown: {_pct(report.benchmark_result.max_drawdown)}",
        f"- Turnover: {_num(report.benchmark_result.turnover)}",
        f"- Average holding period: {_num(report.benchmark_result.average_holding_period)}",
        "- Sector attribution:",
    ])
    if report.benchmark_result.sector_attribution:
        for sector, value in report.benchmark_result.sector_attribution:
            lines.append(f"  - {sector}: {_pct(value)}")
    else:
        lines.append("  - None")

    lines.extend([
        "",
        "## Calibration",
        f"- Calibration error: {_num(report.calibration_result.calibration_error)}",
        f"- Confidence accuracy: {_pct(report.calibration_result.confidence_accuracy)}",
        f"- Replacement accuracy: {_pct(report.calibration_result.replacement_accuracy)}",
        f"- Portfolio allocation quality: {_num(report.calibration_result.portfolio_allocation_quality)}",
        "- Buckets:",
    ])
    for bucket in report.calibration_result.buckets:
        lines.append(
            f"  - {bucket.label}: count={bucket.count}, avg_conf={_num(bucket.average_confidence)}, win_rate={_num(bucket.win_rate)}, error={_num(bucket.error)}"
        )

    lines.extend([
        "",
        "## Drift Analysis",
    ])
    signals = (
        report.drift_result.score_drift,
        report.drift_result.confidence_drift,
        report.drift_result.recommendation_drift,
        report.drift_result.portfolio_drift,
        report.drift_result.thesis_drift,
    )
    for signal in signals:
        lines.append(
            f"- {signal.name}: baseline={_num(signal.baseline)} recent={_num(signal.recent)} delta={_num(signal.delta)} significant={str(signal.significant).lower()}"
        )

    lines.extend(["", "## Failure Cases"])
    if report.failure_cases:
        lines.extend(f"- {item}" for item in report.failure_cases)
    else:
        lines.append("- None")

    lines.extend(["", "## Success Cases"])
    if report.success_cases:
        lines.extend(f"- {item}" for item in report.success_cases)
    else:
        lines.append("- None")

    lines.extend(["", "## Recommended Improvements"])
    if report.recommended_improvements:
        lines.extend(f"- {item}" for item in report.recommended_improvements)
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def write_validation_report(report: ValidationReport, report_path: Path | None = None) -> Path:
    output_path = Path(report_path or report.report_path or DEFAULT_REPORT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.markdown, encoding="utf-8")
    return output_path
