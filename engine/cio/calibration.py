from __future__ import annotations

from dataclasses import dataclass

from .performance_metrics import ConfidenceBucketMetrics, RecommendationCase


@dataclass(frozen=True)
class CalibrationResult:
    buckets: tuple[ConfidenceBucketMetrics, ...]
    expected_calibration_error: float
    calibration_score: float


def _bucket_bounds(confidence: float) -> tuple[str, float, float]:
    score = max(0.0, min(100.0, float(confidence)))
    if score < 20.0:
        return "0-20", 0.0, 20.0
    if score < 40.0:
        return "20-40", 20.0, 40.0
    if score < 60.0:
        return "40-60", 40.0, 60.0
    if score < 80.0:
        return "60-80", 60.0, 80.0
    return "80-100", 80.0, 100.0


def build_calibration(samples: tuple[RecommendationCase, ...]) -> CalibrationResult:
    bucket_order = (
        ("0-20", 0.0, 20.0),
        ("20-40", 20.0, 40.0),
        ("40-60", 40.0, 60.0),
        ("60-80", 60.0, 80.0),
        ("80-100", 80.0, 100.0),
    )
    grouped: dict[str, list[RecommendationCase]] = {label: [] for label, _, _ in bucket_order}
    for sample in samples:
        label, _, _ = _bucket_bounds(sample.confidence)
        grouped[label].append(sample)

    buckets: list[ConfidenceBucketMetrics] = []
    weighted_error = 0.0
    total_count = 0
    for label, lower, upper in bucket_order:
        items = sorted(grouped[label], key=lambda item: (item.decision_id, item.symbol, item.action_type))
        count = len(items)
        total_count += count
        if count == 0:
            buckets.append(
                ConfidenceBucketMetrics(
                    label=label,
                    lower_bound=lower,
                    upper_bound=upper,
                    count=0,
                    average_return=0.0,
                    benchmark_alpha=0.0,
                    win_rate=0.0,
                    calibration_error=0.0,
                    average_confidence=0.0,
                )
            )
            continue

        average_return = sum(item.absolute_return for item in items) / count
        benchmark_alpha = sum(item.benchmark_alpha for item in items) / count
        win_rate = sum(1 for item in items if item.directionally_correct) / count
        average_confidence = sum(item.confidence for item in items) / count
        calibration_error = abs(average_confidence - (win_rate * 100.0))
        weighted_error += calibration_error * count

        buckets.append(
            ConfidenceBucketMetrics(
                label=label,
                lower_bound=lower,
                upper_bound=upper,
                count=count,
                average_return=round(average_return, 6),
                benchmark_alpha=round(benchmark_alpha, 6),
                win_rate=round(win_rate, 6),
                calibration_error=round(calibration_error, 6),
                average_confidence=round(average_confidence, 6),
            )
        )

    expected_calibration_error = (weighted_error / total_count) if total_count else 0.0
    calibration_score = max(0.0, 100.0 - expected_calibration_error)
    return CalibrationResult(
        buckets=tuple(buckets),
        expected_calibration_error=round(expected_calibration_error, 6),
        calibration_score=round(calibration_score, 6),
    )
