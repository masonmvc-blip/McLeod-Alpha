from __future__ import annotations

from collections import defaultdict

from .models import DecisionEngineInputs, MaterialNewsItem, ThesisChange, ThesisHealthResult


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _mean(values: list[float], default: float = 50.0) -> float:
    if not values:
        return default
    return sum(values) / len(values)


def _news_delta(news: MaterialNewsItem) -> float:
    impact = news.impact.strip().lower()
    materiality = _clamp(float(news.materiality_score))
    if impact == "positive":
        return min(18.0, materiality * 0.18)
    if impact == "negative":
        return -min(20.0, materiality * 0.22)
    return 0.0


def compute_thesis_health(inputs: DecisionEngineInputs) -> ThesisHealthResult:
    current_scores = {symbol.upper(): _clamp(float(score)) for symbol, score in inputs.thesis_health_scores.items()}
    news_by_symbol: dict[str, list[MaterialNewsItem]] = defaultdict(list)
    for item in inputs.recent_material_news:
        news_by_symbol[item.symbol.upper()].append(item)

    symbol_scores: dict[str, float] = {}
    changes: list[ThesisChange] = []

    for symbol in sorted(set(current_scores) | set(news_by_symbol)):
        current_score = current_scores.get(symbol, 50.0)
        delta = sum(_news_delta(item) for item in news_by_symbol.get(symbol, ()))
        adjusted_score = _clamp(current_score + delta)
        symbol_scores[symbol] = round(adjusted_score, 2)
        if abs(delta) >= 2.0:
            supporting_evidence = tuple(
                f"{item.headline} ({item.impact}, {item.materiality_score:.0f})" for item in sorted(news_by_symbol.get(symbol, ()), key=lambda row: (row.published_at, row.headline))
            )
            changes.append(
                ThesisChange(
                    symbol=symbol,
                    previous_score=round(current_score, 2),
                    current_score=round(current_score, 2),
                    adjusted_score=round(adjusted_score, 2),
                    delta=round(delta, 2),
                    reason="Material news adjusted the thesis health score.",
                    confidence=round(min(100.0, 50.0 + abs(delta) * 2.0), 2),
                    supporting_evidence=supporting_evidence,
                )
            )

    news_items = tuple(
        sorted(
            inputs.recent_material_news,
            key=lambda item: (-_clamp(float(item.materiality_score)), item.symbol.upper(), item.headline, item.published_at),
        )
    )

    overall_score = _mean(list(symbol_scores.values()), default=_mean(list(current_scores.values()), default=50.0))
    return ThesisHealthResult(
        overall_score=round(_clamp(overall_score), 2),
        symbol_scores=tuple(sorted(symbol_scores.items())),
        changes=tuple(sorted(changes, key=lambda change: (-abs(change.delta), change.symbol))),
        material_news=news_items,
    )