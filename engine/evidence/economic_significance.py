from __future__ import annotations

from typing import Mapping


def economic_significance(metrics: Mapping[str, object]) -> float:
    return float(metrics.get("annual_alpha", metrics.get("CAGR", 0.0)))