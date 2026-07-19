from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from .historical_replay import HistoricalReplayResult


@dataclass(frozen=True)
class CalibrationBucket:
    label: str
    count: int
    average_confidence: float
    win_rate: float
    error: float


@dataclass(frozen=True)
class CalibrationAnalysisResult:
    calibration_error: float
    confidence_accuracy: float
    replacement_accuracy: float
    portfolio_allocation_quality: float
    buckets: tuple[CalibrationBucket, ...] = field(default_factory=tuple)


def _bucket_label(confidence: float) -> str:
    if confidence < 20:
        return "0-20"
    if confidence < 40:
        return "20-40"
    if confidence < 60:
        return "40-60"
    if confidence < 80:
        return "60-80"
    return "80-100"


def _allocation_quality(weights: tuple[tuple[str, float], ...]) -> float:
    if not weights:
        return 0.0
    total = sum(max(0.0, float(weight)) for _, weight in weights)
    if total <= 0:
        return 0.0
    normalized = [max(0.0, float(weight)) / total for _, weight in weights]
    herfindahl = sum(value * value for value in normalized)
    quality = max(0.0, min(100.0, (1.0 - herfindahl) * 100.0))
    return quality


def analyze_calibration(replay: HistoricalReplayResult) -> CalibrationAnalysisResult:
    points = list(replay.points)
    if not points:
        return CalibrationAnalysisResult(
            calibration_error=0.0,
            confidence_accuracy=0.0,
            replacement_accuracy=0.0,
            portfolio_allocation_quality=0.0,
            buckets=(),
        )

    grouped: dict[str, list[tuple[float, float]]] = {}
    replacement_hits = 0
    allocation_scores: list[float] = []
    confidence_correct_count = 0

    for point in points:
        realized = 100.0 if point.cio_return > 0 else 0.0
        grouped.setdefault(_bucket_label(point.confidence_score), []).append((point.confidence_score, realized))
        if point.replacement_success:
            replacement_hits += 1
        allocation_scores.append(_allocation_quality(point.portfolio_weights))
        prediction = point.confidence_score >= 50.0
        actual = point.cio_return > 0
        if prediction == actual:
            confidence_correct_count += 1

    ordered_labels = ("0-20", "20-40", "40-60", "60-80", "80-100")
    buckets: list[CalibrationBucket] = []
    errors: list[float] = []

    for label in ordered_labels:
        samples = grouped.get(label, [])
        if not samples:
            bucket = CalibrationBucket(label=label, count=0, average_confidence=0.0, win_rate=0.0, error=0.0)
        else:
            avg_conf = mean(item[0] for item in samples)
            win_rate = mean(item[1] for item in samples)
            error = abs(avg_conf - win_rate)
            errors.append(error)
            bucket = CalibrationBucket(
                label=label,
                count=len(samples),
                average_confidence=round(avg_conf, 6),
                win_rate=round(win_rate, 6),
                error=round(error, 6),
            )
        buckets.append(bucket)

    calibration_error = mean(errors) if errors else 0.0
    confidence_accuracy = confidence_correct_count / len(points)

    return CalibrationAnalysisResult(
        calibration_error=round(calibration_error, 6),
        confidence_accuracy=round(confidence_accuracy, 6),
        replacement_accuracy=round(replacement_hits / len(points), 6),
        portfolio_allocation_quality=round(mean(allocation_scores), 6),
        buckets=tuple(buckets),
    )
