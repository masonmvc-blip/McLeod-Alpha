from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from engine.cio.calibration import CalibrationResult
from engine.cio.learning_report import PerformanceReport
from engine.cio.performance_lab import PerformanceLab, PerformanceLabInputs
from engine.cio.performance_metrics import ConfidenceBucketMetrics, PerformanceMetrics
from engine.cio.recommendation_analysis import RecommendationAnalysis
from engine.cio.decision_record import DecisionRecord, build_decision_id
from engine.cio.models import DailyCIOBrief, PortfolioHolding, MaterialNewsItem, ActionRecommendation, ThesisChange
from engine.cio.outcome_reconciliation import RealizedOutcome
from engine.cio.portfolio_plan import AllocationChange, PortfolioPlan, PortfolioTargetPosition, RequiredAction, ReplacementCandidate
from engine.cio.risk_budget import RiskBudget


def _record(*, date: str, symbol: str, action_type: str, recommendation: str, confidence: float, priority: int = 1) -> DecisionRecord:
    return DecisionRecord(
        decision_id=build_decision_id(
            as_of_date=date,
            symbol=symbol,
            action_type=action_type,
            recommendation=recommendation,
            source_brief_id="BRIEF-2026-07-18-XYZ",
        ),
        created_at=f"{date}T00:00:00+00:00",
        as_of_date=date,
        symbol=symbol,
        action_type=action_type,
        priority=priority,
        recommendation=recommendation,
        confidence=confidence,
        expected_benefit="benefit",
        expected_risk="risk",
        supporting_evidence=("evidence",),
        conflicting_evidence=(),
        assumptions=("assumption",),
        invalidation_conditions=("invalidation",),
        source_brief_id="BRIEF-2026-07-18-XYZ",
        status="OPEN",
    )


def _outcome(*, decision_id: str, abs_return: float, benchmark_alpha: float, correct: bool, evaluation_date: str = "2026-07-20") -> RealizedOutcome:
    return RealizedOutcome(
        absolute_return=abs_return,
        benchmark_adjusted_return=benchmark_alpha,
        directionally_correct=correct,
        confidence_bucket="HIGH",
        thesis_outcome="validated" if correct else "impaired",
        evaluation_date=evaluation_date,
        notes=("holding_period_days=3",),
        decision_id=decision_id,
    )


def _brief() -> DailyCIOBrief:
    return DailyCIOBrief(
        date="2026-07-18",
        portfolio_health_score=74.0,
        portfolio_health_components=(("quality", 75.0),),
        overall_risk="MODERATE",
        cash_recommendation="Raise cash toward 15%.",
        top_actions=(
            ActionRecommendation(priority=1, title="Trim XOM", reason="Energy risk rose", expected_benefit="Reduce drag", confidence=70.0, supporting_evidence=("XOM news",), symbol="XOM", action_type="trim"),
            ActionRecommendation(priority=2, title="Buy AAPL", reason="Setup improved", expected_benefit="Capture upside", confidence=90.0, supporting_evidence=("AAPL news",), symbol="AAPL", action_type="buy"),
            ActionRecommendation(priority=3, title="Hold TSM", reason="No rush", expected_benefit="Preserve capital", confidence=45.0, supporting_evidence=("TSM news",), symbol="TSM", action_type="hold"),
        ),
        recommended_buys=(
            ActionRecommendation(priority=1, title="Buy AAPL", reason="Setup improved", expected_benefit="Capture upside", confidence=90.0, supporting_evidence=("AAPL news",), symbol="AAPL", action_type="buy"),
            ActionRecommendation(priority=2, title="Buy MELI", reason="Momentum healthy", expected_benefit="Add alpha", confidence=85.0, supporting_evidence=("MELI news",), symbol="MELI", action_type="buy"),
        ),
        recommended_trims=(
            ActionRecommendation(priority=1, title="Trim XOM", reason="Energy risk rose", expected_benefit="Reduce drag", confidence=70.0, supporting_evidence=("XOM news",), symbol="XOM", action_type="trim"),
        ),
        holds=(
            ActionRecommendation(priority=1, title="Hold TSM", reason="No rush", expected_benefit="Preserve capital", confidence=45.0, supporting_evidence=("TSM news",), symbol="TSM", action_type="hold"),
        ),
        watchlist_changes=(),
        thesis_changes=(
            ThesisChange(symbol="LOWC", previous_score=42.0, current_score=43.0, adjusted_score=45.0, delta=3.0, reason="positive drift", confidence=55.0, supporting_evidence=("LOWC note",)),
            ThesisChange(symbol="AAPL", previous_score=70.0, current_score=71.0, adjusted_score=76.0, delta=6.0, reason="positive drift", confidence=90.0, supporting_evidence=("AAPL note",)),
            ThesisChange(symbol="MSFT", previous_score=68.0, current_score=67.0, adjusted_score=63.0, delta=-4.0, reason="mixed drift", confidence=55.0, supporting_evidence=("MSFT note",)),
            ThesisChange(symbol="XOM", previous_score=52.0, current_score=51.0, adjusted_score=43.0, delta=-8.0, reason="negative drift", confidence=70.0, supporting_evidence=("XOM note",)),
            ThesisChange(symbol="TSM", previous_score=64.0, current_score=65.0, adjusted_score=67.0, delta=2.0, reason="positive drift", confidence=45.0, supporting_evidence=("TSM note",)),
            ThesisChange(symbol="MELI", previous_score=72.0, current_score=73.0, adjusted_score=78.0, delta=5.0, reason="positive drift", confidence=85.0, supporting_evidence=("MELI note",)),
        ),
        material_news=(
            MaterialNewsItem(symbol="XOM", headline="Margins compress", summary="Energy weakness", impact="negative", materiality_score=80, source="Reuters", published_at="2026-07-18T08:00:00-05:00"),
            MaterialNewsItem(symbol="AAPL", headline="Demand stays firm", summary="Positive", impact="positive", materiality_score=66, source="Reuters", published_at="2026-07-18T08:05:00-05:00"),
        ),
        confidence_score=72.0,
        executive_summary="Daily CIO brief summary.",
    )


def _plan() -> PortfolioPlan:
    return PortfolioPlan(
        date="2026-07-18",
        current_portfolio=(
            PortfolioHolding(symbol="LOWC", quantity=10, market_value=1000, sector="Speculative"),
            PortfolioHolding(symbol="AAPL", quantity=10, market_value=2000, sector="Technology"),
            PortfolioHolding(symbol="MSFT", quantity=10, market_value=2000, sector="Technology"),
            PortfolioHolding(symbol="XOM", quantity=10, market_value=2000, sector="Energy"),
            PortfolioHolding(symbol="TSM", quantity=10, market_value=2000, sector="Semiconductors"),
            PortfolioHolding(symbol="MELI", quantity=10, market_value=2000, sector="Consumer Internet"),
        ),
        target_portfolio=(
            PortfolioTargetPosition(symbol="AAPL", current_weight=0.15, target_weight=0.18, current_value=2000, target_value=2400, action="Increase", score=82.0, expected_alpha=0.08, expected_risk=0.22, reason="AAPL", supporting_evidence=("AAPL",)),
            PortfolioTargetPosition(symbol="MELI", current_weight=0.10, target_weight=0.16, current_value=2000, target_value=2200, action="Increase", score=80.0, expected_alpha=0.05, expected_risk=0.24, reason="MELI", supporting_evidence=("MELI",)),
            PortfolioTargetPosition(symbol="XOM", current_weight=0.20, target_weight=0.08, current_value=2000, target_value=800, action="Reduce", score=35.0, expected_alpha=-0.03, expected_risk=0.55, reason="XOM", supporting_evidence=("XOM",)),
        ),
        required_actions=(
            RequiredAction(priority=1, text="Reduce XOM to 8.0%", symbol="XOM", action_type="reduce"),
            RequiredAction(priority=2, text="Increase AAPL to 18.0%", symbol="AAPL", action_type="increase"),
        ),
        replacement_candidates=(
            ReplacementCandidate(symbol_to_sell="XOM", symbol_to_buy="MELI", expected_alpha_gain=0.08, confidence=88.0, supporting_evidence=("XOM->MELI",), rationale="Better growth"),
            ReplacementCandidate(symbol_to_sell="TSM", symbol_to_buy="LOWC", expected_alpha_gain=-0.04, confidence=64.0, supporting_evidence=("TSM->LOWC",), rationale="Bad idea"),
        ),
        allocation_changes=(
            AllocationChange(symbol="AAPL", current_weight=0.15, target_weight=0.18, delta_weight=0.03, current_value=2000, target_value=2400, action="Increase", reason="AAPL"),
            AllocationChange(symbol="XOM", current_weight=0.20, target_weight=0.08, delta_weight=-0.12, current_value=2000, target_value=800, action="Reduce", reason="XOM"),
        ),
        cash_target=0.15,
        risk_budget=RiskBudget(concentration=0.22, sector_exposure=(("Technology", 0.34), ("Energy", 0.08)), cash_exposure=0.15, expected_volatility=24.0, largest_risks=("Energy concentration",), largest_opportunities=("AAPL alpha",)),
        expected_portfolio_alpha=0.06,
        expected_portfolio_risk=0.24,
        confidence=76.0,
        executive_summary="Portfolio plan summary.",
    )


def _inputs() -> PerformanceLabInputs:
    records = (
        _record(date="2026-07-18", symbol="LOWC", action_type="buy", recommendation="Buy LOWC", confidence=10.0, priority=1),
        _record(date="2026-07-18", symbol="AAPL", action_type="buy", recommendation="Buy AAPL", confidence=90.0, priority=2),
        _record(date="2026-07-18", symbol="MSFT", action_type="buy", recommendation="Buy MSFT", confidence=55.0, priority=3),
        _record(date="2026-07-18", symbol="XOM", action_type="trim", recommendation="Trim XOM", confidence=70.0, priority=4),
        _record(date="2026-07-18", symbol="TSM", action_type="hold", recommendation="Hold TSM", confidence=45.0, priority=5),
        _record(date="2026-07-18", symbol="CASH", action_type="cash", recommendation="Raise cash toward 15%", confidence=30.0, priority=6),
        _record(date="2026-07-18", symbol="MELI", action_type="buy", recommendation="Buy MELI", confidence=85.0, priority=7),
    )
    return PerformanceLabInputs(
        decision_records=records,
        realized_outcomes=(
            _outcome(decision_id=records[0].decision_id, abs_return=-0.03, benchmark_alpha=-0.04, correct=False),
            _outcome(decision_id=records[1].decision_id, abs_return=0.12, benchmark_alpha=0.08, correct=True),
            _outcome(decision_id=records[2].decision_id, abs_return=-0.08, benchmark_alpha=-0.12, correct=False),
            _outcome(decision_id=records[3].decision_id, abs_return=-0.05, benchmark_alpha=-0.03, correct=True),
            _outcome(decision_id=records[4].decision_id, abs_return=0.02, benchmark_alpha=0.02, correct=True),
            _outcome(decision_id=records[5].decision_id, abs_return=0.00, benchmark_alpha=-0.01, correct=True),
            _outcome(decision_id=records[6].decision_id, abs_return=0.05, benchmark_alpha=0.05, correct=True),
        ),
        portfolio_plans=(_plan(),),
        daily_briefs=(_brief(),),
    )


def test_performance_lab_generates_stable_report(tmp_path):
    lab = PerformanceLab()
    report_one = lab.generate(_inputs(), report_path=tmp_path / "first" / "artifacts" / "cio" / "performance_report.md")
    report_two = lab.generate(_inputs(), report_path=tmp_path / "second" / "artifacts" / "cio" / "performance_report.md")

    assert report_one.metrics == report_two.metrics
    assert report_one.calibration == report_two.calibration
    assert report_one.analysis == report_two.analysis
    assert report_one.markdown == report_two.markdown
    assert (tmp_path / "first" / "artifacts" / "cio" / "performance_report.md").exists()
    assert report_one.metrics.overall_win_rate == pytest.approx(5 / 7, rel=1e-6)
    assert report_one.metrics.directional_accuracy == pytest.approx(5 / 7, rel=1e-6)
    assert report_one.metrics.benchmark_alpha == pytest.approx(-0.007143, rel=1e-6)
    assert report_one.metrics.average_return == pytest.approx(0.004286, rel=1e-6)
    assert report_one.metrics.median_return == pytest.approx(0.0, rel=1e-6)
    assert report_one.metrics.buy_accuracy == pytest.approx(2 / 4, rel=1e-6)
    assert report_one.metrics.trim_accuracy == pytest.approx(1.0, rel=1e-6)
    assert report_one.metrics.cash_timing_accuracy == pytest.approx(1.0, rel=1e-6)
    assert report_one.metrics.thesis_prediction_accuracy == pytest.approx(5 / 6, rel=1e-6)
    assert report_one.metrics.replacement_accuracy == pytest.approx(0.5, rel=1e-6)
    assert report_one.metrics.portfolio_alpha == pytest.approx(0.06, rel=1e-6)
    assert "## Executive Summary" in report_one.markdown
    assert "## Recommendation Accuracy" in report_one.markdown
    assert "## Confidence Calibration" in report_one.markdown
    assert "## Alpha Attribution" in report_one.markdown
    assert "## Failure Analysis" in report_one.markdown
    assert "## Success Analysis" in report_one.markdown
    assert "## Suggested Areas for Improvement" in report_one.markdown
    assert "## Open Questions" in report_one.markdown


def test_confidence_calibration_and_analysis(tmp_path):
    report = PerformanceLab().generate(_inputs(), report_path=tmp_path / "performance_report.md")

    labels = [bucket.label for bucket in report.calibration.buckets]
    counts = [bucket.count for bucket in report.calibration.buckets]

    assert labels == ["0-20", "20-40", "40-60", "60-80", "80-100"]
    assert counts == [1, 1, 2, 1, 2]
    assert report.calibration.buckets[0].calibration_error == pytest.approx(10.0, rel=1e-6)
    assert report.calibration.buckets[4].calibration_error == pytest.approx(12.5, rel=1e-6)
    assert report.metrics.confidence_calibration == pytest.approx(80.714286, rel=1e-6)
    assert report.analysis.best_recommendation_types[0].label == "hold"
    assert report.analysis.worst_recommendation_types[0].label == "trim"
    assert report.analysis.best_sectors[0].label == "Consumer Internet"
    assert report.analysis.worst_sectors[0].label == "Speculative"
    assert report.analysis.largest_mistakes[0].symbol == "MSFT"
    assert report.analysis.largest_successes[0].symbol == "AAPL"
    assert any("Weak action type: buy" in pattern for pattern in report.analysis.recurring_failure_patterns)
    assert any("Replacement misses: TSM->LOWC" in pattern for pattern in report.analysis.recurring_failure_patterns)


def test_report_dataclass_is_immutable():
    report = PerformanceReport(
        generated_at="2026-07-19T00:00:00",
        metrics=PerformanceMetrics(
            overall_win_rate=0.0,
            directional_accuracy=0.0,
            benchmark_alpha=0.0,
            recommendation_precision=0.0,
            recommendation_recall=0.0,
            average_return=0.0,
            median_return=0.0,
            average_holding_period=0.0,
            portfolio_alpha=0.0,
            buy_accuracy=0.0,
            trim_accuracy=0.0,
            cash_timing_accuracy=0.0,
            confidence_calibration=0.0,
            thesis_prediction_accuracy=0.0,
            replacement_accuracy=0.0,
            closed_recommendation_count=0,
            measurable_recommendation_count=0,
            confidence_buckets=(),
        ),
        calibration=CalibrationResult(buckets=(), expected_calibration_error=0.0, calibration_score=100.0),
        analysis=RecommendationAnalysis(best_recommendation_types=(), worst_recommendation_types=(), best_sectors=(), worst_sectors=(), largest_mistakes=(), largest_successes=(), recurring_failure_patterns=()),
        report_path="artifacts/cio/performance_report.md",
        markdown="",
        source_summary=(),
    )

    with pytest.raises(FrozenInstanceError):
        report.generated_at = "x"  # type: ignore[misc]
