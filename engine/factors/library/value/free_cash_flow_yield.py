from __future__ import annotations
from engine.factors.library import factor, number, ratio

def evaluate(snapshot): return ratio(number(snapshot, "free_cash_flow"), number(snapshot, "enterprise_value"), "enterprise value")

FACTOR = factor(factor_id="value.free_cash_flow_yield", name="Free Cash Flow Yield", category="VALUE", rationale="Free cash flow relative to enterprise value is a raw cash-return valuation measure.", fields=("free_cash_flow", "enterprise_value"), evaluator=evaluate)