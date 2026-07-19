from __future__ import annotations
from engine.factors.library import factor, number, ratio

def evaluate(snapshot): return -ratio(number(snapshot, "net_debt"), number(snapshot, "free_cash_flow"), "free cash flow")

FACTOR = factor(factor_id="balance_sheet.net_debt_to_fcf", name="Net Debt to Free Cash Flow", category="BALANCE_SHEET", rationale="Higher net debt relative to recurring free cash flow increases balance-sheet burden.", fields=("net_debt", "free_cash_flow"), evaluator=evaluate)