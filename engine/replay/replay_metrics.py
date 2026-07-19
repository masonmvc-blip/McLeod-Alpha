from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ReplayMetrics:
    decision_stability: float
    recommendation_changes: int
    thesis_health_evolution: tuple[tuple[str, float], ...]
    portfolio_turnover: float
    replacement_quality: float
    alpha_over_time: tuple[tuple[str, float], ...]
    confidence_calibration: float
    max_drawdown: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_stability": self.decision_stability,
            "recommendation_changes": self.recommendation_changes,
            "thesis_health_evolution": [list(item) for item in self.thesis_health_evolution],
            "portfolio_turnover": self.portfolio_turnover,
            "replacement_quality": self.replacement_quality,
            "alpha_over_time": [list(item) for item in self.alpha_over_time],
            "confidence_calibration": self.confidence_calibration,
            "max_drawdown": self.max_drawdown,
        }


def _round6(value: float) -> float:
    return round(float(value), 6)


def _max_drawdown(values: list[float]) -> float:
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = peak - value
        max_dd = max(max_dd, drawdown)
    return _round6(max_dd)


def compute_replay_metrics(day_results: tuple[dict[str, Any], ...]) -> ReplayMetrics:
    recommendations: list[str] = []
    thesis_health: list[tuple[str, float]] = []
    turnover_values: list[float] = []
    replacement_quality_values: list[float] = []
    alpha_curve: list[tuple[str, float]] = []
    calibration_errors: list[float] = []

    cumulative_alpha = 0.0

    for day in day_results:
        date_value = str(day["snapshot_date"])
        thesis = dict(day["stages"]["thesis"]["payload"])
        decision = dict(day["stages"]["decision"]["payload"])
        portfolio = dict(day["stages"]["portfolio"]["payload"])
        performance = dict(day["stages"]["performance"]["payload"])

        recommendations.append(str(decision.get("recommendation") or "HOLD"))
        thesis_health.append((date_value, _round6(float(thesis.get("health_score") or 0.0))))
        turnover_values.append(float(portfolio.get("turnover") or 0.0))
        replacement_quality_values.append(float(performance.get("replacement_quality") or 0.0))

        alpha_value = float(performance.get("alpha") or 0.0)
        cumulative_alpha += alpha_value
        alpha_curve.append((date_value, _round6(cumulative_alpha)))

        confidence = float(decision.get("confidence") or 0.0)
        realized = float(performance.get("realized_direction") or 0.0)
        calibration_errors.append(abs(confidence - realized))

    changes = 0
    stable_pairs = 0
    total_pairs = max(0, len(recommendations) - 1)
    for index in range(1, len(recommendations)):
        if recommendations[index] == recommendations[index - 1]:
            stable_pairs += 1
        else:
            changes += 1

    decision_stability = _round6((stable_pairs / total_pairs) if total_pairs else 1.0)
    portfolio_turnover = _round6(sum(turnover_values) / len(turnover_values)) if turnover_values else 0.0
    replacement_quality = _round6(sum(replacement_quality_values) / len(replacement_quality_values)) if replacement_quality_values else 0.0
    confidence_calibration = _round6(1.0 - (sum(calibration_errors) / len(calibration_errors))) if calibration_errors else 1.0

    return ReplayMetrics(
        decision_stability=decision_stability,
        recommendation_changes=changes,
        thesis_health_evolution=tuple(thesis_health),
        portfolio_turnover=portfolio_turnover,
        replacement_quality=replacement_quality,
        alpha_over_time=tuple(alpha_curve),
        confidence_calibration=confidence_calibration,
        max_drawdown=_max_drawdown([value for _, value in alpha_curve]),
    )
