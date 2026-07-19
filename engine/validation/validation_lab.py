from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .benchmark_analysis import BenchmarkAnalysisResult, analyze_benchmarks
from .calibration_analysis import CalibrationAnalysisResult, analyze_calibration
from .drift_detection import DriftDetectionResult, detect_drift
from .historical_replay import HistoricalReplayResult, ReplayPoint, run_historical_replay
from .validation_report import DEFAULT_REPORT_PATH, ValidationReport, render_validation_report, write_validation_report


@dataclass(frozen=True)
class ValidationLabInputs:
    replay_points: tuple[ReplayPoint, ...]


class ValidationLab:
    def validate(self, inputs: ValidationLabInputs, *, report_path: Path | None = None) -> ValidationReport:
        replay_result = run_historical_replay(inputs.replay_points)
        benchmark_result = analyze_benchmarks(replay_result)
        calibration_result = analyze_calibration(replay_result)
        drift_result = detect_drift(replay_result)

        failure_cases = self._failure_cases(replay_result)
        success_cases = self._success_cases(replay_result)
        recommended_improvements = self._recommended_improvements(drift_result, calibration_result)

        generated_at = self._deterministic_generated_at(replay_result)
        report = ValidationReport(
            generated_at=generated_at,
            replay_result=replay_result,
            benchmark_result=benchmark_result,
            calibration_result=calibration_result,
            drift_result=drift_result,
            failure_cases=failure_cases,
            success_cases=success_cases,
            recommended_improvements=recommended_improvements,
            report_path=str(report_path or DEFAULT_REPORT_PATH),
            markdown="",
        )
        markdown = render_validation_report(report)
        report = ValidationReport(
            generated_at=report.generated_at,
            replay_result=report.replay_result,
            benchmark_result=report.benchmark_result,
            calibration_result=report.calibration_result,
            drift_result=report.drift_result,
            failure_cases=report.failure_cases,
            success_cases=report.success_cases,
            recommended_improvements=report.recommended_improvements,
            report_path=report.report_path,
            markdown=markdown,
        )
        write_validation_report(report, report_path=report_path)
        return report

    @staticmethod
    def _deterministic_generated_at(replay_result: HistoricalReplayResult) -> str:
        if not replay_result.points:
            return "1970-01-01T00:00:00+00:00"
        last_date = max(point.as_of_date for point in replay_result.points)
        return f"{last_date}T00:00:00+00:00"

    @staticmethod
    def _failure_cases(replay_result: HistoricalReplayResult) -> tuple[str, ...]:
        failures = [
            f"{point.as_of_date}: CIO return {point.cio_return:+.2%}"
            for point in replay_result.points
            if point.cio_return < 0
        ]
        return tuple(sorted(failures))

    @staticmethod
    def _success_cases(replay_result: HistoricalReplayResult) -> tuple[str, ...]:
        successes = [
            f"{point.as_of_date}: CIO return {point.cio_return:+.2%}"
            for point in replay_result.points
            if point.cio_return > 0
        ]
        return tuple(sorted(successes))

    @staticmethod
    def _recommended_improvements(
        drift_result: DriftDetectionResult,
        calibration_result: CalibrationAnalysisResult,
    ) -> tuple[str, ...]:
        suggestions: list[str] = []
        if drift_result.significant_drifts:
            suggestions.append("Investigate statistically significant drifts across score/confidence/recommendation/portfolio/thesis dimensions.")
        if calibration_result.calibration_error > 12.0:
            suggestions.append("Review confidence calibration bands and evidence weighting assumptions.")
        if calibration_result.portfolio_allocation_quality < 35.0:
            suggestions.append("Improve portfolio allocation quality by reducing concentration.")
        if calibration_result.replacement_accuracy < 0.5:
            suggestions.append("Revisit replacement candidate selection quality.")
        return tuple(suggestions)
