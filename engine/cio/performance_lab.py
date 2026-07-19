from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median

from .calibration import CalibrationResult, build_calibration
from .decision_record import DecisionRecord
from .learning_report import PerformanceReport, DEFAULT_REPORT_PATH, render_learning_report, write_learning_report
from .outcome_reconciliation import RealizedOutcome
from .performance_metrics import PerformanceMetrics, RecommendationCase
from .portfolio_plan import PortfolioPlan
from .recommendation_analysis import RecommendationAnalysis, build_recommendation_analysis
from .models import DailyCIOBrief


@dataclass(frozen=True)
class PerformanceLabInputs:
    decision_records: tuple[DecisionRecord, ...]
    realized_outcomes: tuple[RealizedOutcome, ...]
    portfolio_plans: tuple[PortfolioPlan, ...] = ()
    daily_briefs: tuple[DailyCIOBrief, ...] = ()


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_action_type(action_type: str) -> str:
    action = str(action_type or "").strip().lower()
    if action in {"buy", "buy_to_open", "increase", "add", "long", "enter", "open"}:
        return "buy"
    if action in {"trim", "sell", "reduce", "exit", "close"}:
        return "trim"
    if action == "cash":
        return "cash"
    if action == "hold":
        return "hold"
    return action or "other"


def _parse_iso_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _holding_period_days(record: DecisionRecord, outcome: RealizedOutcome) -> float:
    start_dt = _parse_iso_datetime(record.created_at)
    end_dt = _parse_iso_datetime(outcome.evaluation_date)
    if start_dt is None or end_dt is None:
        for note in outcome.notes:
            if note.startswith("holding_period_days="):
                try:
                    return float(note.split("=", 1)[1])
                except ValueError:
                    return 0.0
        return 0.0
    return max(0.0, (end_dt.date() - start_dt.date()).days)


def _cash_posture_from_text(text: str) -> str:
    lowered = _normalize_text(text).lower()
    if any(token in lowered for token in ("raise cash", "maintain cash", "hold cash", "preserve capital")):
        return "defensive"
    if any(token in lowered for token in ("deploy cash", "deploy up to", "put cash", "increase risk")):
        return "aggressive"
    return "neutral"


def _build_sector_lookup(plans: tuple[PortfolioPlan, ...], briefs: tuple[DailyCIOBrief, ...]) -> dict[str, str]:
    sector_lookup: dict[str, str] = {}
    for plan in plans:
        for holding in plan.current_portfolio:
            sector_lookup.setdefault(holding.symbol.upper(), holding.sector or "Unknown")
    for brief in briefs:
        for change in brief.thesis_changes:
            sector_lookup.setdefault(change.symbol.upper(), "Unknown")
        for action in (*brief.top_actions, *brief.recommended_buys, *brief.recommended_trims, *brief.holds):
            sector_lookup.setdefault(action.symbol.upper(), "Unknown")
    return sector_lookup


def _build_thesis_delta_lookup(briefs: tuple[DailyCIOBrief, ...]) -> dict[str, float]:
    lookup: dict[str, float] = {}
    for brief in briefs:
        for change in brief.thesis_changes:
            lookup[change.symbol.upper()] = float(change.delta)
    return lookup


def _build_replacement_accuracy_lookup(inputs: PerformanceLabInputs, outcome_lookup: dict[str, RealizedOutcome]) -> dict[str, bool]:
    accuracy: dict[str, bool] = {}
    symbol_lookup = {
        sample.symbol.upper(): sample
        for sample in _build_recommendation_samples(inputs, outcome_lookup, _build_sector_lookup(inputs.portfolio_plans, inputs.daily_briefs))
    }
    for plan in inputs.portfolio_plans:
        for candidate in plan.replacement_candidates:
            sell_outcome = symbol_lookup.get(candidate.symbol_to_sell.upper())
            buy_outcome = symbol_lookup.get(candidate.symbol_to_buy.upper())
            if sell_outcome is None or buy_outcome is None:
                continue
            accuracy[f"{candidate.symbol_to_sell.upper()}->{candidate.symbol_to_buy.upper()}"] = buy_outcome.benchmark_alpha > sell_outcome.benchmark_alpha
    return accuracy


def _build_recommendation_samples(
    inputs: PerformanceLabInputs,
    outcome_lookup: dict[str, RealizedOutcome],
    sector_lookup: dict[str, str],
) -> tuple[RecommendationCase, ...]:
    samples: list[RecommendationCase] = []
    for record in sorted(inputs.decision_records, key=lambda item: (item.as_of_date, item.symbol, item.decision_id)):
        outcome = outcome_lookup.get(record.decision_id)
        if outcome is None:
            continue
        action_type = _normalize_action_type(record.action_type)
        sector = sector_lookup.get(record.symbol.upper(), "Unknown")
        recommendation_text = record.recommendation
        posture = _cash_posture_from_text(recommendation_text) if action_type == "cash" else "neutral"
        if action_type == "buy":
            correct = outcome.benchmark_adjusted_return > 0.0
        elif action_type == "trim":
            correct = outcome.benchmark_adjusted_return < 0.0
        elif action_type == "cash":
            correct = (posture == "defensive" and outcome.benchmark_adjusted_return <= 0.0) or (posture == "aggressive" and outcome.benchmark_adjusted_return > 0.0)
        elif action_type == "hold":
            correct = abs(outcome.benchmark_adjusted_return) <= 0.03
        else:
            correct = outcome.directionally_correct

        thesis_delta = None
        for brief in inputs.daily_briefs:
            for change in brief.thesis_changes:
                if change.symbol.upper() == record.symbol.upper():
                    thesis_delta = float(change.delta)
                    break
            if thesis_delta is not None:
                break

        samples.append(
            RecommendationCase(
                decision_id=record.decision_id,
                symbol=record.symbol.upper(),
                action_type=action_type,
                sector=sector,
                confidence=float(record.confidence),
                absolute_return=float(outcome.absolute_return),
                benchmark_alpha=float(outcome.benchmark_adjusted_return),
                directionally_correct=bool(correct),
                holding_period_days=_holding_period_days(record, outcome),
                recommendation_text=record.recommendation,
                thesis_delta=thesis_delta,
                source_label="journal",
            )
        )
    return tuple(samples)


class PerformanceLab:
    def generate(self, inputs: PerformanceLabInputs, *, report_path: Path | None = None) -> PerformanceReport:
        outcome_lookup = {outcome.decision_id: outcome for outcome in inputs.realized_outcomes}
        sector_lookup = _build_sector_lookup(inputs.portfolio_plans, inputs.daily_briefs)
        thesis_delta_lookup = _build_thesis_delta_lookup(inputs.daily_briefs)
        recommendation_samples = _build_recommendation_samples(inputs, outcome_lookup, sector_lookup)
        replacement_accuracy_lookup = _build_replacement_accuracy_lookup(inputs, outcome_lookup)

        calibration = build_calibration(recommendation_samples)
        analysis = build_recommendation_analysis(
            recommendation_samples,
            sector_lookup=sector_lookup,
            thesis_delta_lookup=thesis_delta_lookup,
            replacement_accuracy_lookup=replacement_accuracy_lookup,
        )
        metrics = self._build_metrics(
            inputs=inputs,
            samples=recommendation_samples,
            calibration=calibration,
            replacement_accuracy_lookup=replacement_accuracy_lookup,
        )

        generated_at = self._deterministic_generated_at(inputs)
        report = PerformanceReport(
            generated_at=generated_at,
            metrics=metrics,
            calibration=calibration,
            analysis=analysis,
            report_path=str(report_path or DEFAULT_REPORT_PATH),
            markdown="",
            source_summary=self._build_source_summary(inputs),
        )
        markdown = render_learning_report(report)
        report = PerformanceReport(
            generated_at=report.generated_at,
            metrics=report.metrics,
            calibration=report.calibration,
            analysis=report.analysis,
            report_path=report.report_path,
            markdown=markdown,
            source_summary=report.source_summary,
        )
        write_learning_report(report, report_path=report_path)
        return report

    @staticmethod
    def _deterministic_generated_at(inputs: PerformanceLabInputs) -> str:
        outcome_dates = sorted(
            {
                str(outcome.evaluation_date or "").strip()
                for outcome in inputs.realized_outcomes
                if str(outcome.evaluation_date or "").strip()
            }
        )
        if outcome_dates:
            return f"{outcome_dates[-1]}T00:00:00+00:00"

        decision_dates = sorted(
            {
                str(record.as_of_date or "").strip()
                for record in inputs.decision_records
                if str(record.as_of_date or "").strip()
            }
        )
        if decision_dates:
            return f"{decision_dates[-1]}T00:00:00+00:00"

        return "1970-01-01T00:00:00+00:00"

    @staticmethod
    def _build_source_summary(inputs: PerformanceLabInputs) -> tuple[tuple[str, int], ...]:
        return tuple(
            sorted(
                (
                    ("decision_records", len(inputs.decision_records)),
                    ("realized_outcomes", len(inputs.realized_outcomes)),
                    ("portfolio_plans", len(inputs.portfolio_plans)),
                    ("daily_briefs", len(inputs.daily_briefs)),
                ),
                key=lambda item: item[0],
            )
        )

    def _build_metrics(
        self,
        *,
        inputs: PerformanceLabInputs,
        samples: tuple[RecommendationCase, ...],
        calibration: CalibrationResult,
        replacement_accuracy_lookup: dict[str, bool],
    ) -> PerformanceMetrics:
        if not samples:
            return PerformanceMetrics(
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
                confidence_buckets=calibration.buckets,
            )

        closed_count = len(samples)
        correct_samples = [sample for sample in samples if sample.directionally_correct]
        overall_win_rate = len(correct_samples) / closed_count if closed_count else 0.0
        directional_accuracy = sum(1 for sample in samples if sample.directionally_correct) / closed_count if closed_count else 0.0
        benchmark_alpha = mean(sample.benchmark_alpha for sample in samples)
        average_return = mean(sample.absolute_return for sample in samples)
        median_return = median(sample.absolute_return for sample in samples)
        average_holding_period = mean(sample.holding_period_days for sample in samples)

        measurable_recommendation_count = sum(1 for sample in samples if sample.confidence >= 60.0)
        recommendation_precision = sum(1 for sample in samples if sample.confidence >= 60.0 and sample.directionally_correct) / measurable_recommendation_count if measurable_recommendation_count else 0.0
        recommendation_recall = sum(1 for sample in samples if sample.directionally_correct and sample.confidence >= 60.0) / len(correct_samples) if correct_samples else 0.0

        buy_samples = [sample for sample in samples if sample.action_type == "buy"]
        trim_samples = [sample for sample in samples if sample.action_type == "trim"]
        cash_samples = [sample for sample in samples if sample.action_type == "cash"]

        buy_accuracy = sum(1 for sample in buy_samples if sample.directionally_correct) / len(buy_samples) if buy_samples else 0.0
        trim_accuracy = sum(1 for sample in trim_samples if sample.directionally_correct) / len(trim_samples) if trim_samples else 0.0
        cash_timing_accuracy = sum(1 for sample in cash_samples if sample.directionally_correct) / len(cash_samples) if cash_samples else 0.0

        thesis_samples = [sample for sample in samples if sample.thesis_delta is not None]
        thesis_prediction_accuracy = (
            sum(1 for sample in thesis_samples if (sample.thesis_delta or 0.0) * sample.benchmark_alpha > 0.0) / len(thesis_samples)
            if thesis_samples
            else 0.0
        )

        replacement_accuracy = (
            sum(1 for accurate in replacement_accuracy_lookup.values() if accurate) / len(replacement_accuracy_lookup)
            if replacement_accuracy_lookup
            else 0.0
        )

        portfolio_alpha = self._portfolio_alpha(inputs)
        confidence_calibration = calibration.calibration_score

        return PerformanceMetrics(
            overall_win_rate=round(overall_win_rate, 6),
            directional_accuracy=round(directional_accuracy, 6),
            benchmark_alpha=round(benchmark_alpha, 6),
            recommendation_precision=round(recommendation_precision, 6),
            recommendation_recall=round(recommendation_recall, 6),
            average_return=round(average_return, 6),
            median_return=round(median_return, 6),
            average_holding_period=round(average_holding_period, 6),
            portfolio_alpha=round(portfolio_alpha, 6),
            buy_accuracy=round(buy_accuracy, 6),
            trim_accuracy=round(trim_accuracy, 6),
            cash_timing_accuracy=round(cash_timing_accuracy, 6),
            confidence_calibration=round(confidence_calibration, 6),
            thesis_prediction_accuracy=round(thesis_prediction_accuracy, 6),
            replacement_accuracy=round(replacement_accuracy, 6),
            closed_recommendation_count=closed_count,
            measurable_recommendation_count=measurable_recommendation_count,
            confidence_buckets=calibration.buckets,
        )

    @staticmethod
    def _portfolio_alpha(inputs: PerformanceLabInputs) -> float:
        portfolio_alphas = [float(plan.expected_portfolio_alpha) for plan in inputs.portfolio_plans if plan is not None]
        return mean(portfolio_alphas) if portfolio_alphas else 0.0
