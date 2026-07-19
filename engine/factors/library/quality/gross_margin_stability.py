from __future__ import annotations
from engine.factors.library import average, factor, series

def evaluate(snapshot):
    values = series(snapshot, "gross_margin_history")
    mean = average(values)
    variability = average([(value - mean) ** 2 for value in values]) ** 0.5
    deterioration = max(0.0, values[0] - values[-1])
    return mean - variability - deterioration

FACTOR = factor(factor_id="quality.gross_margin_stability", name="Gross Margin Stability", category="QUALITY", rationale="Stable, non-deteriorating gross margins support durable pricing power.", fields=("gross_margin_history",), evaluator=evaluate)