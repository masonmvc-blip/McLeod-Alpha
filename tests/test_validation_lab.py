from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from engine.validation.validation_lab import ValidationLab, ValidationLabInputs
from engine.validation.historical_replay import ReplayPoint, run_historical_replay


def _points() -> tuple[ReplayPoint, ...]:
    return (
        ReplayPoint(
            as_of_date="2026-07-10",
            research_score=74.0,
            thesis_score=76.0,
            confidence_score=72.0,
            recommendations=("Buy AAPL", "Trim XOM"),
            portfolio_weights=(("AAPL", 0.25), ("MSFT", 0.20), ("XOM", 0.10), ("CASH", 0.45)),
            cio_return=0.012,
            spy_return=0.010,
            equal_weight_return=0.009,
            benchmark_return=0.008,
            turnover=0.22,
            average_holding_period=4.0,
            replacement_success=True,
            sector_returns=(("Technology", 0.014), ("Energy", -0.003)),
        ),
        ReplayPoint(
            as_of_date="2026-07-11",
            research_score=73.0,
            thesis_score=75.0,
            confidence_score=70.0,
            recommendations=("Buy TSM", "Hold AAPL"),
            portfolio_weights=(("AAPL", 0.22), ("TSM", 0.16), ("MSFT", 0.18), ("CASH", 0.44)),
            cio_return=0.006,
            spy_return=0.004,
            equal_weight_return=0.005,
            benchmark_return=0.004,
            turnover=0.18,
            average_holding_period=5.0,
            replacement_success=True,
            sector_returns=(("Technology", 0.008), ("Semiconductors", 0.009)),
        ),
        ReplayPoint(
            as_of_date="2026-07-12",
            research_score=71.0,
            thesis_score=74.0,
            confidence_score=68.0,
            recommendations=("Trim XOM",),
            portfolio_weights=(("AAPL", 0.24), ("MSFT", 0.19), ("XOM", 0.09), ("CASH", 0.48)),
            cio_return=-0.008,
            spy_return=-0.006,
            equal_weight_return=-0.007,
            benchmark_return=-0.006,
            turnover=0.20,
            average_holding_period=4.5,
            replacement_success=False,
            sector_returns=(("Technology", -0.006), ("Energy", -0.012)),
        ),
        ReplayPoint(
            as_of_date="2026-07-13",
            research_score=60.0,
            thesis_score=61.0,
            confidence_score=58.0,
            recommendations=("Hold AAPL",),
            portfolio_weights=(("AAPL", 0.30), ("MSFT", 0.24), ("XOM", 0.10), ("CASH", 0.36)),
            cio_return=-0.014,
            spy_return=-0.010,
            equal_weight_return=-0.011,
            benchmark_return=-0.010,
            turnover=0.30,
            average_holding_period=3.0,
            replacement_success=False,
            sector_returns=(("Technology", -0.015), ("Energy", -0.005)),
        ),
        ReplayPoint(
            as_of_date="2026-07-14",
            research_score=58.0,
            thesis_score=59.0,
            confidence_score=56.0,
            recommendations=("Buy MELI",),
            portfolio_weights=(("AAPL", 0.32), ("MSFT", 0.26), ("MELI", 0.10), ("CASH", 0.32)),
            cio_return=0.009,
            spy_return=0.008,
            equal_weight_return=0.007,
            benchmark_return=0.008,
            turnover=0.28,
            average_holding_period=3.2,
            replacement_success=False,
            sector_returns=(("Technology", 0.010), ("Consumer", 0.012)),
        ),
        ReplayPoint(
            as_of_date="2026-07-15",
            research_score=57.0,
            thesis_score=58.0,
            confidence_score=54.0,
            recommendations=("Hold MELI",),
            portfolio_weights=(("AAPL", 0.34), ("MSFT", 0.27), ("MELI", 0.11), ("CASH", 0.28)),
            cio_return=0.004,
            spy_return=0.005,
            equal_weight_return=0.005,
            benchmark_return=0.004,
            turnover=0.26,
            average_holding_period=3.4,
            replacement_success=False,
            sector_returns=(("Technology", 0.004), ("Consumer", 0.006)),
        ),
    )


def test_historical_replay_determinism_and_no_future_leakage():
    result_one = run_historical_replay(_points())
    result_two = run_historical_replay(_points())

    assert result_one == result_two
    assert all(stage.research_stage == "completed" for stage in result_one.stage_results)

    unsorted = (_points()[1], _points()[0])
    with pytest.raises(ValueError):
        run_historical_replay(unsorted)


def test_validation_metrics_and_benchmark_comparison(tmp_path):
    report = ValidationLab().validate(ValidationLabInputs(replay_points=_points()), report_path=tmp_path / "validation_report.md")

    assert report.benchmark_result.alpha_vs_spy == pytest.approx(-0.000333, rel=1e-6)
    assert report.benchmark_result.alpha_vs_equal_weight == pytest.approx(0.000167, rel=1e-6)
    assert report.benchmark_result.alpha_vs_benchmark_portfolio == pytest.approx(0.000167, rel=1e-6)
    assert report.benchmark_result.hit_rate == pytest.approx(4 / 6, rel=1e-6)
    assert report.benchmark_result.max_drawdown > 0
    assert report.calibration_result.replacement_accuracy == pytest.approx(2 / 6, rel=1e-6)
    assert report.calibration_result.confidence_accuracy > 0
    assert report.calibration_result.portfolio_allocation_quality > 0


def test_drift_detection_and_report_generation(tmp_path):
    report = ValidationLab().validate(ValidationLabInputs(replay_points=_points()), report_path=tmp_path / "validation_report.md")

    assert any(signal.name == "score_drift" for signal in report.drift_result.significant_drifts)
    assert any(signal.name == "thesis_drift" for signal in report.drift_result.significant_drifts)
    assert "## Executive Summary" in report.markdown
    assert "## Historical Replay Results" in report.markdown
    assert "## Benchmark Comparison" in report.markdown
    assert "## Calibration" in report.markdown
    assert "## Drift Analysis" in report.markdown
    assert "## Failure Cases" in report.markdown
    assert "## Success Cases" in report.markdown
    assert "## Recommended Improvements" in report.markdown


def test_stable_replay_byte_identical_reruns(tmp_path):
    one = ValidationLab().validate(ValidationLabInputs(replay_points=_points()), report_path=tmp_path / "one" / "validation_report.md")
    two = ValidationLab().validate(ValidationLabInputs(replay_points=_points()), report_path=tmp_path / "two" / "validation_report.md")

    first_bytes = (tmp_path / "one" / "validation_report.md").read_bytes()
    second_bytes = (tmp_path / "two" / "validation_report.md").read_bytes()
    assert one.replay_result == two.replay_result
    assert one.benchmark_result == two.benchmark_result
    assert one.calibration_result == two.calibration_result
    assert one.drift_result == two.drift_result
    assert one.failure_cases == two.failure_cases
    assert one.success_cases == two.success_cases
    assert one.recommended_improvements == two.recommended_improvements
    assert one.markdown == two.markdown
    assert first_bytes == second_bytes

    with pytest.raises(FrozenInstanceError):
        one.generated_at = "x"  # type: ignore[misc]
