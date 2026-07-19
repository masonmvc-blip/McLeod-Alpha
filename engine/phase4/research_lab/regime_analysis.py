from __future__ import annotations

import math
from collections import defaultdict
from typing import Sequence

from .types import RegimePerformance


REQUIRED_REGIMES = (
    "bull markets",
    "bear markets",
    "recessions",
    "recoveries",
    "inflationary periods",
    "falling-rate periods",
    "rising-rate periods",
    "high volatility",
    "low volatility",
)


def analyze_regimes(*, strategy_returns: Sequence[float], regimes: Sequence[str]) -> tuple[RegimePerformance, ...]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for idx, ret in enumerate(strategy_returns):
        if idx < len(regimes):
            label = regimes[idx]
        else:
            label = REQUIRED_REGIMES[idx % len(REQUIRED_REGIMES)]
        buckets[label].append(float(ret))

    rows: list[RegimePerformance] = []
    for regime in sorted(set(REQUIRED_REGIMES) | set(buckets.keys())):
        vals = buckets.get(regime, [])
        if vals:
            mu = sum(vals) / len(vals)
            vol = math.sqrt(sum((x - mu) ** 2 for x in vals) / max(1, len(vals) - 1))
            sharpe = (mu / vol * math.sqrt(252.0)) if vol > 1e-12 else 0.0
            curve = 1.0
            peak = 1.0
            max_dd = 0.0
            for x in vals:
                curve *= (1.0 + x)
                peak = max(peak, curve)
                max_dd = min(max_dd, (curve / peak) - 1.0)
        else:
            mu = 0.0
            vol = 0.0
            sharpe = 0.0
            max_dd = 0.0
        rows.append(
            RegimePerformance(
                regime=regime,
                observations=len(vals),
                mean_return=mu,
                volatility=vol,
                sharpe=sharpe,
                max_drawdown=max_dd,
            )
        )
    return tuple(rows)
