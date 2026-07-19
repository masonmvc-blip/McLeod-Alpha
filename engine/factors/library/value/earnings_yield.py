from __future__ import annotations
from engine.factors.library import factor, number, ratio

def evaluate(snapshot): return ratio(number(snapshot, "operating_earnings"), number(snapshot, "enterprise_value"), "enterprise value")

FACTOR = factor(factor_id="value.earnings_yield", name="Earnings Yield", category="VALUE", rationale="Operating earnings relative to enterprise value is a capital-structure-neutral valuation measure.", fields=("operating_earnings", "enterprise_value"), evaluator=evaluate)