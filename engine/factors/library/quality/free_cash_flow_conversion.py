from __future__ import annotations
from engine.factors.library import average, factor, ratio, series

def evaluate(snapshot):
    fcf, income = series(snapshot, "free_cash_flow_history"), series(snapshot, "net_income_history")
    if len(fcf) != len(income): raise ValueError("malformed input: history lengths differ")
    return average([ratio(value, income[index], "net income") for index, value in enumerate(fcf)])

FACTOR = factor(factor_id="quality.free_cash_flow_conversion", name="Free Cash Flow Conversion", category="QUALITY", rationale="Cash conversion measures how reliably reported earnings become distributable cash.", fields=("free_cash_flow_history", "net_income_history"), evaluator=evaluate)