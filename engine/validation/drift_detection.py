from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from .historical_replay import HistoricalReplayResult


@dataclass(frozen=True)
class DriftSignal:
    name: str
    baseline: float
    recent: float
    delta: float
    significant: bool


@dataclass(frozen=True)
class DriftDetectionResult:
    score_drift: DriftSignal
    confidence_drift: DriftSignal
    recommendation_drift: DriftSignal
    portfolio_drift: DriftSignal
    thesis_drift: DriftSignal
    significant_drifts: tuple[DriftSignal, ...] = field(default_factory=tuple)


def _signal(name: str, baseline: float, recent: float, threshold: float) -> DriftSignal:
    delta = recent - baseline
    significant = abs(delta) >= threshold
    return DriftSignal(
        name=name,
        baseline=round(baseline, 6),
        recent=round(recent, 6),
        delta=round(delta, 6),
        significant=significant,
    )


def _recommendation_size(points) -> float:
    if not points:
        return 0.0
    return mean(float(len(point.recommendations)) for point in points)


def _portfolio_concentration(points) -> float:
    values: list[float] = []
    for point in points:
        total = sum(max(0.0, weight) for _, weight in point.portfolio_weights)
        if total <= 0:
            values.append(1.0)
            continue
        normalized = [max(0.0, weight) / total for _, weight in point.portfolio_weights]
        values.append(sum(weight * weight for weight in normalized))
    return mean(values) if values else 0.0


def detect_drift(replay: HistoricalReplayResult) -> DriftDetectionResult:
    points = list(replay.points)
    if len(points) < 2:
        zero = _signal("insufficient", 0.0, 0.0, 1.0)
        return DriftDetectionResult(
            score_drift=zero,
            confidence_drift=zero,
            recommendation_drift=zero,
            portfolio_drift=zero,
            thesis_drift=zero,
            significant_drifts=(),
        )

    split = max(1, len(points) // 2)
    baseline_points = points[:split]
    recent_points = points[split:]

    score_drift = _signal(
        "score_drift",
        mean(point.research_score for point in baseline_points),
        mean(point.research_score for point in recent_points),
        threshold=5.0,
    )
    confidence_drift = _signal(
        "confidence_drift",
        mean(point.confidence_score for point in baseline_points),
        mean(point.confidence_score for point in recent_points),
        threshold=5.0,
    )
    recommendation_drift = _signal(
        "recommendation_drift",
        _recommendation_size(baseline_points),
        _recommendation_size(recent_points),
        threshold=1.0,
    )
    portfolio_drift = _signal(
        "portfolio_drift",
        _portfolio_concentration(baseline_points),
        _portfolio_concentration(recent_points),
        threshold=0.05,
    )
    thesis_drift = _signal(
        "thesis_drift",
        mean(point.thesis_score for point in baseline_points),
        mean(point.thesis_score for point in recent_points),
        threshold=5.0,
    )

    all_signals = (score_drift, confidence_drift, recommendation_drift, portfolio_drift, thesis_drift)
    significant = tuple(signal for signal in all_signals if signal.significant)

    return DriftDetectionResult(
        score_drift=score_drift,
        confidence_drift=confidence_drift,
        recommendation_drift=recommendation_drift,
        portfolio_drift=portfolio_drift,
        thesis_drift=thesis_drift,
        significant_drifts=significant,
    )
