from __future__ import annotations
from engine.factors.library import factor, ratio, series

def evaluate(snapshot):
    profit, capital = series(snapshot, "operating_profit_history"), series(snapshot, "invested_capital_history")
    if len(profit) < 2 or len(profit) != len(capital): raise ValueError("malformed input: reinvestment histories")
    return ratio(profit[-1] - profit[0], capital[-1] - capital[0], "incremental invested capital")

FACTOR = factor(factor_id="capital_allocation.reinvestment_efficiency", name="Reinvestment Efficiency", category="CAPITAL_ALLOCATION", rationale="Incremental operating profit per incremental invested capital measures reinvestment quality.", fields=("operating_profit_history", "invested_capital_history"), evaluator=evaluate)