from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from .performance_metrics import GroupPerformanceMetrics, RecommendationCase


@dataclass(frozen=True)
class RecommendationAnalysis:
    best_recommendation_types: tuple[GroupPerformanceMetrics, ...]
    worst_recommendation_types: tuple[GroupPerformanceMetrics, ...]
    best_sectors: tuple[GroupPerformanceMetrics, ...]
    worst_sectors: tuple[GroupPerformanceMetrics, ...]
    largest_mistakes: tuple[RecommendationCase, ...]
    largest_successes: tuple[RecommendationCase, ...]
    recurring_failure_patterns: tuple[str, ...] = field(default_factory=tuple)


def _group_samples(samples: tuple[RecommendationCase, ...], *, key_fn) -> tuple[GroupPerformanceMetrics, ...]:
    grouped: dict[str, list[RecommendationCase]] = {}
    for sample in samples:
        grouped.setdefault(key_fn(sample), []).append(sample)

    results: list[GroupPerformanceMetrics] = []
    for label, items in grouped.items():
        count = len(items)
        average_return = mean(item.absolute_return for item in items) if items else 0.0
        benchmark_alpha = mean(item.benchmark_alpha for item in items) if items else 0.0
        win_rate = sum(1 for item in items if item.directionally_correct) / count if count else 0.0
        average_holding_period = mean(item.holding_period_days for item in items) if items else 0.0
        results.append(
            GroupPerformanceMetrics(
                label=label,
                count=count,
                average_return=round(average_return, 6),
                benchmark_alpha=round(benchmark_alpha, 6),
                win_rate=round(win_rate, 6),
                average_holding_period=round(average_holding_period, 6),
            )
        )

    return tuple(sorted(results, key=lambda item: (item.label, item.count)))


def _top_items(samples: tuple[RecommendationCase, ...], *, reverse: bool) -> tuple[RecommendationCase, ...]:
    ordered = sorted(
        samples,
        key=lambda item: (
            item.benchmark_alpha,
            item.absolute_return,
            item.confidence,
            item.symbol,
            item.decision_id,
        ),
        reverse=reverse,
    )
    return tuple(ordered[:3])


def build_recommendation_analysis(
    samples: tuple[RecommendationCase, ...],
    *,
    sector_lookup: dict[str, str],
    thesis_delta_lookup: dict[str, float],
    replacement_accuracy_lookup: dict[str, bool],
) -> RecommendationAnalysis:
    enriched_samples = tuple(
        RecommendationCase(
            decision_id=sample.decision_id,
            symbol=sample.symbol,
            action_type=sample.action_type,
            sector=sector_lookup.get(sample.symbol.upper(), sample.sector or "Unknown"),
            confidence=sample.confidence,
            absolute_return=sample.absolute_return,
            benchmark_alpha=sample.benchmark_alpha,
            directionally_correct=sample.directionally_correct,
            holding_period_days=sample.holding_period_days,
            recommendation_text=sample.recommendation_text,
            thesis_delta=thesis_delta_lookup.get(sample.symbol.upper(), sample.thesis_delta),
            source_label=sample.source_label,
        )
        for sample in samples
    )

    type_groups = _group_samples(enriched_samples, key_fn=lambda item: _normalize_action_type(item.action_type))
    sector_groups = _group_samples(enriched_samples, key_fn=lambda item: item.sector or "Unknown")

    best_types = tuple(sorted(type_groups, key=lambda item: (-item.benchmark_alpha, -item.win_rate, item.label))[:3])
    worst_types = tuple(sorted(type_groups, key=lambda item: (item.benchmark_alpha, item.win_rate, item.label))[:3])
    best_sectors = tuple(sorted(sector_groups, key=lambda item: (-item.benchmark_alpha, -item.win_rate, item.label))[:3])
    worst_sectors = tuple(sorted(sector_groups, key=lambda item: (item.benchmark_alpha, item.win_rate, item.label))[:3])

    largest_mistakes = _top_items(tuple(item for item in enriched_samples if not item.directionally_correct), reverse=False)
    largest_successes = _top_items(tuple(item for item in enriched_samples if item.directionally_correct), reverse=True)

    failure_patterns = _derive_failure_patterns(
        samples=enriched_samples,
        type_groups=type_groups,
        sector_groups=sector_groups,
        replacement_accuracy_lookup=replacement_accuracy_lookup,
    )

    return RecommendationAnalysis(
        best_recommendation_types=best_types,
        worst_recommendation_types=worst_types,
        best_sectors=best_sectors,
        worst_sectors=worst_sectors,
        largest_mistakes=largest_mistakes,
        largest_successes=largest_successes,
        recurring_failure_patterns=failure_patterns,
    )


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


def _derive_failure_patterns(
    *,
    samples: tuple[RecommendationCase, ...],
    type_groups: tuple[GroupPerformanceMetrics, ...],
    sector_groups: tuple[GroupPerformanceMetrics, ...],
    replacement_accuracy_lookup: dict[str, bool],
) -> tuple[str, ...]:
    patterns: list[str] = []

    high_confidence_misses = [item for item in samples if item.confidence >= 80.0 and not item.directionally_correct]
    if high_confidence_misses:
        patterns.append(f"High-confidence misses: {len(high_confidence_misses)} recommendations above 80 confidence failed.")

    weak_types = [group for group in type_groups if group.benchmark_alpha < 0.0 and group.count >= 2]
    for group in weak_types[:2]:
        patterns.append(f"Weak action type: {group.label} averaged {group.benchmark_alpha:+.2%} benchmark alpha.")

    weak_sectors = [group for group in sector_groups if group.benchmark_alpha < 0.0 and group.count >= 2]
    for group in weak_sectors[:2]:
        patterns.append(f"Weak sector: {group.label} averaged {group.benchmark_alpha:+.2%} benchmark alpha.")

    cash_misses = [item for item in samples if _normalize_action_type(item.action_type) == "cash" and not item.directionally_correct]
    if cash_misses:
        patterns.append(f"Cash timing misses: {len(cash_misses)} cash recommendations were mistimed.")

    replacement_misses = [symbol for symbol, accurate in sorted(replacement_accuracy_lookup.items()) if not accurate]
    if replacement_misses:
        patterns.append(f"Replacement misses: {', '.join(replacement_misses)}.")

    thesis_misses = [item for item in samples if item.thesis_delta is not None and item.thesis_delta * item.benchmark_alpha < 0.0]
    if thesis_misses:
        patterns.append(f"Thesis forecast mismatches: {len(thesis_misses)} symbols moved against thesis direction.")

    return tuple(patterns[:5])
