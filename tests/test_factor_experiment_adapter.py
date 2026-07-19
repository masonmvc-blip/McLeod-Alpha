from __future__ import annotations

from engine.research_lab.factor_experiment_adapter import evaluate_registered_factor


def _snapshot() -> dict:
    return {"snapshot_id": "A", "snapshot_date": "2026-07-19", "content_hash": "lineage", "company_fundamentals": {"free_cash_flow": 100.0, "enterprise_value": 1000.0}}


def test_registered_factor_loading_determinism_and_missing_diagnostics() -> None:
    first = evaluate_registered_factor(factor_id="value.free_cash_flow_yield", version="1.0.0", snapshots=(_snapshot(),))
    assert first == evaluate_registered_factor(factor_id="value.free_cash_flow_yield", version="1.0.0", snapshots=(_snapshot(),))
    assert first[0].signal == 0.1 and first[0].source_lineage == "lineage"
    missing = _snapshot(); del missing["company_fundamentals"]["free_cash_flow"]
    assert "missing required input" in (evaluate_registered_factor(factor_id="value.free_cash_flow_yield", version="1.0.0", snapshots=(missing,))[0].rejection_reason or "")


def test_adapter_preserves_future_rejections_without_silent_loss() -> None:
    future = _snapshot(); future["company_fundamentals"]["free_cash_flow"] = {"value": 100.0, "publication_date": "2026-07-20"}
    result = evaluate_registered_factor(factor_id="value.free_cash_flow_yield", version="1.0.0", snapshots=(future,))
    assert result[0].signal is None and "future-dated observation rejected" in (result[0].rejection_reason or "")