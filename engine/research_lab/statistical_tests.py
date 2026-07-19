from __future__ import annotations

from math import erf, sqrt
from random import Random
from typing import Sequence


def bootstrap_confidence_interval(values: Sequence[float], *, seed: int, samples: int = 1000) -> tuple[float, float]:
    rng, values = Random(seed), tuple(float(value) for value in values)
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(samples))
    return means[int(samples * .025)], means[int(samples * .975)]


def t_test(values: Sequence[float]) -> dict[str, float]:
    mean = sum(values) / len(values); variance = sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1)
    statistic = mean / sqrt(variance / len(values)) if variance else 0.0
    return {"statistic": statistic, "p_value": 1.0 - erf(abs(statistic) / sqrt(2.0))}


def mann_whitney(left: Sequence[float], right: Sequence[float]) -> dict[str, float]:
    combined = sorted([(float(value), 0, index) for index, value in enumerate(left)] + [(float(value), 1, index) for index, value in enumerate(right)])
    ranks = {(group, index): rank + 1 for rank, (_, group, index) in enumerate(combined)}
    u = sum(ranks[(0, index)] for index in range(len(left))) - len(left) * (len(left) + 1) / 2
    return {"u_statistic": u, "p_value": 1.0}


def effect_size(values: Sequence[float]) -> float:
    mean = sum(values) / len(values); deviation = sqrt(sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1))
    return mean / deviation if deviation else 0.0


def train_test_split(values: Sequence[float]) -> dict[str, float]:
    split = max(1, len(values) // 2)
    return {"train_mean": sum(values[:split]) / split, "test_mean": sum(values[split:]) / max(1, len(values) - split)}


def stability(values: Sequence[float]) -> float:
    split = train_test_split(values)
    return 1.0 - abs(split["train_mean"] - split["test_mean"])