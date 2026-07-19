from __future__ import annotations
from engine.factors.library import average, factor, series

def evaluate(snapshot):
    values = series(snapshot, "roic_history")
    mean = average(values)
    variability = average([(value - mean) ** 2 for value in values]) ** 0.5
    return mean - variability

FACTOR = factor(factor_id="quality.roic_persistence", name="ROIC Persistence", category="QUALITY", rationale="Sustained high returns on invested capital indicate durable business quality.", fields=("roic_history",), evaluator=evaluate)