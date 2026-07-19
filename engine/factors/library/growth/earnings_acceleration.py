from __future__ import annotations
from engine.factors.library import factor, series

def evaluate(snapshot):
    values = series(snapshot, "operating_income_growth_history")
    if len(values) < 2: raise ValueError("missing required input: two earnings-growth periods")
    return values[-1] - values[-2]

FACTOR = factor(factor_id="growth.earnings_acceleration", name="Earnings Acceleration", category="GROWTH", rationale="Accelerating operating earnings can indicate improving operating leverage.", fields=("operating_income_growth_history",), evaluator=evaluate)