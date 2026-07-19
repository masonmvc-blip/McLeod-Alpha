from __future__ import annotations
from engine.factors.library import factor, ratio, series

def evaluate(snapshot):
    values = series(snapshot, "diluted_share_count_history")
    if len(values) < 2: raise ValueError("missing required input: two share-count periods")
    return ratio(values[0] - values[-1], values[0], "initial diluted shares")

FACTOR = factor(factor_id="capital_allocation.share_count_reduction", name="Share Count Reduction", category="CAPITAL_ALLOCATION", rationale="Genuine diluted-share reduction can increase each owner's claim on future cash flows.", fields=("diluted_share_count_history",), evaluator=evaluate)