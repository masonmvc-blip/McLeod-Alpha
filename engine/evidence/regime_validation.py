from __future__ import annotations

from typing import Mapping


def regime_stability_score(statistics: Mapping[str, object]) -> float:
    stability = statistics.get("stability", {})
    if not isinstance(stability, Mapping):
        return 0.0
    value = stability.get("score", stability.get("stability_score", 0.0))
    return float(value)