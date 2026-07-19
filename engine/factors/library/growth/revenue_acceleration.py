from __future__ import annotations
from engine.factors.library import factor, series

def evaluate(snapshot):
    values = series(snapshot, "revenue_growth_history")
    if len(values) < 2: raise ValueError("missing required input: two revenue-growth periods")
    return values[-1] - values[-2]

FACTOR = factor(factor_id="growth.revenue_acceleration", name="Revenue Acceleration", category="GROWTH", rationale="Improving revenue growth can signal strengthening demand and operating momentum.", fields=("revenue_growth_history",), evaluator=evaluate)