from __future__ import annotations

from hashlib import sha256
from typing import Sequence

from .types import FeatureImportanceScore


def _deterministic_unit_interval(seed_text: str) -> float:
    raw = sha256(seed_text.encode("utf-8")).hexdigest()[:12]
    return int(raw, 16) / float(16 ** 12 - 1)


def rank_feature_importance(
    factors: Sequence[str],
    *,
    strategy_returns: Sequence[float],
) -> tuple[FeatureImportanceScore, ...]:
    base = abs(sum(strategy_returns)) / max(1, len(strategy_returns))
    rows: list[FeatureImportanceScore] = []
    for factor in sorted(set(factors)):
        predictive = min(1.0, base + _deterministic_unit_interval(f"pred|{factor}") * 0.3)
        stability = _deterministic_unit_interval(f"stab|{factor}")
        persistence = _deterministic_unit_interval(f"pers|{factor}")
        interactions = _deterministic_unit_interval(f"int|{factor}")
        marginal = predictive * (0.5 + persistence / 2.0)
        redundancy = _deterministic_unit_interval(f"red|{factor}")
        score = (
            0.30 * predictive
            + 0.20 * stability
            + 0.20 * persistence
            + 0.15 * interactions
            + 0.15 * marginal
            - 0.10 * redundancy
        )
        rows.append(
            FeatureImportanceScore(
                factor=factor,
                predictive_contribution=predictive,
                stability=stability,
                persistence=persistence,
                interaction_effects=interactions,
                marginal_improvement=marginal,
                redundancy=redundancy,
                composite_score=score,
            )
        )
    rows.sort(key=lambda row: (-row.composite_score, row.factor))
    return tuple(rows)
