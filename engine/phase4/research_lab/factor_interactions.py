from __future__ import annotations

from itertools import combinations
from typing import Sequence

from .types import InteractionEvaluation, InteractionType


def evaluate_factor_interactions(
    factors: Sequence[str],
    *,
    strategy_returns: Sequence[float],
) -> tuple[InteractionEvaluation, ...]:
    factor_list = sorted(set(factors))
    base = abs(sum(strategy_returns)) / max(1, len(strategy_returns))
    rows: list[InteractionEvaluation] = []
    for size in (1, 2, 3):
        for combo in combinations(factor_list, min(size, len(factor_list))):
            strength = base * len(combo)
            if strength > 0.03:
                interaction_type = InteractionType.ADDITIVE
            elif strength < 0.01:
                interaction_type = InteractionType.DESTRUCTIVE
            else:
                interaction_type = InteractionType.NEUTRAL
            rows.append(
                InteractionEvaluation(
                    factors=tuple(combo),
                    interaction_type=interaction_type,
                    incremental_return=strength,
                    incremental_sharpe=strength * 10.0,
                )
            )
        if len(factor_list) < size:
            break
    rows.sort(key=lambda row: (-row.incremental_sharpe, row.factors))
    return tuple(rows)
