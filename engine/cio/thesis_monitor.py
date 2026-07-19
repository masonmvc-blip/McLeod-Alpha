from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from .thesis_evidence import EvidenceSummary


@dataclass(frozen=True)
class ThesisHealthBreakdown:
    supporting_component: float
    contradictory_component: float
    recency_component: float
    materiality_component: float
    consistency_component: float
    health_score: float
    explanation: tuple[str, ...] = field(default_factory=tuple)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(mean(values))


def compute_thesis_health(summary: EvidenceSummary) -> ThesisHealthBreakdown:
    support_weights = [item.weighted_impact for item in summary.supporting]
    contradictory_weights = [item.weighted_impact for item in summary.contradictory]
    neutral_weights = [item.weighted_impact for item in summary.neutral]

    support_component = _avg(support_weights)
    contradictory_component = _avg(contradictory_weights)

    all_items = list(summary.supporting) + list(summary.contradictory) + list(summary.neutral) + list(summary.unknown)
    recency_component = _avg([item.recency for item in all_items])
    materiality_component = _avg([item.materiality for item in all_items])

    resolved_count = len(summary.supporting) + len(summary.contradictory) + len(summary.neutral)
    contradiction_ratio = (len(summary.contradictory) / resolved_count) if resolved_count else 0.0
    consistency_component = _clamp(100.0 - (contradiction_ratio * 100.0))

    base = 50.0
    health_score = _clamp(
        base
        + (support_component * 0.30)
        - (contradictory_component * 0.35)
        + ((recency_component - 50.0) * 0.15)
        + ((materiality_component - 50.0) * 0.10)
        + ((consistency_component - 50.0) * 0.20)
    )

    explanation = (
        f"Base score: {base:.2f}",
        f"Supporting evidence component (+): {support_component:.2f}",
        f"Contradictory evidence component (-): {contradictory_component:.2f}",
        f"Recency component: {recency_component:.2f}",
        f"Materiality component: {materiality_component:.2f}",
        f"Consistency component: {consistency_component:.2f}",
        f"Final thesis health score: {health_score:.2f}",
    )

    return ThesisHealthBreakdown(
        supporting_component=round(support_component, 6),
        contradictory_component=round(contradictory_component, 6),
        recency_component=round(recency_component, 6),
        materiality_component=round(materiality_component, 6),
        consistency_component=round(consistency_component, 6),
        health_score=round(health_score, 6),
        explanation=explanation,
    )
