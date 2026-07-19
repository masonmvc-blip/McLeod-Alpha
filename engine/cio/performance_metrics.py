from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConfidenceBucketMetrics:
    label: str
    lower_bound: float
    upper_bound: float
    count: int
    average_return: float
    benchmark_alpha: float
    win_rate: float
    calibration_error: float
    average_confidence: float


@dataclass(frozen=True)
class GroupPerformanceMetrics:
    label: str
    count: int
    average_return: float
    benchmark_alpha: float
    win_rate: float
    average_holding_period: float


@dataclass(frozen=True)
class RecommendationCase:
    decision_id: str
    symbol: str
    action_type: str
    sector: str
    confidence: float
    absolute_return: float
    benchmark_alpha: float
    directionally_correct: bool
    holding_period_days: float
    recommendation_text: str = ""
    thesis_delta: float | None = None
    source_label: str = "journal"


@dataclass(frozen=True)
class PerformanceMetrics:
    overall_win_rate: float
    directional_accuracy: float
    benchmark_alpha: float
    recommendation_precision: float
    recommendation_recall: float
    average_return: float
    median_return: float
    average_holding_period: float
    portfolio_alpha: float
    buy_accuracy: float
    trim_accuracy: float
    cash_timing_accuracy: float
    confidence_calibration: float
    thesis_prediction_accuracy: float
    replacement_accuracy: float
    closed_recommendation_count: int
    measurable_recommendation_count: int
    confidence_buckets: tuple[ConfidenceBucketMetrics, ...] = field(default_factory=tuple)
