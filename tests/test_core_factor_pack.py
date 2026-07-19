from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from engine.factors import FactorRegistry, validate_registry
from engine.factors.library import core_factors


def _snapshot() -> dict:
    return {
        "snapshot_date": "2026-07-19",
        "company_fundamentals": {
            "roic_history": [0.10, 0.15, 0.20], "gross_margin_history": [0.40, 0.42, 0.45],
            "free_cash_flow_history": [80.0, 100.0, 120.0], "net_income_history": [100.0, 110.0, 120.0],
            "revenue_growth_history": [0.05, 0.12], "operating_income_growth_history": [0.02, 0.10],
            "free_cash_flow": 120.0, "enterprise_value": 1000.0, "operating_earnings": 150.0,
            "diluted_share_count_history": [100.0, 95.0], "operating_profit_history": [100.0, 130.0],
            "invested_capital_history": [500.0, 600.0], "net_debt": 200.0,
        },
    }


def _factor(factor_id: str):
    return next(item for item in core_factors() if item.metadata.factor_id == factor_id)


def test_all_core_factors_register_with_complete_experimental_metadata() -> None:
    factors = core_factors()
    registry = FactorRegistry()
    for item in reversed(factors): registry.register(item)
    assert len(factors) == 10
    assert tuple(item.metadata.factor_id for item in registry.factors()) == tuple(sorted(item.metadata.factor_id for item in factors))
    assert all(item.metadata.version == "1.0.0" and item.metadata.status == "EXPERIMENTAL" for item in factors)
    assert all(item.metadata.evidence_required and not item.metadata.retired for item in factors)
    assert validate_registry(registry)["valid"]


@pytest.mark.parametrize("factor_id", [item.metadata.factor_id for item in core_factors()])
def test_factors_are_deterministic_and_do_not_mutate_snapshot(factor_id: str) -> None:
    factor = _factor(factor_id); snapshot = _snapshot(); before = deepcopy(snapshot)
    assert factor.evaluate(snapshot) == factor.evaluate(snapshot)
    assert snapshot == before


@pytest.mark.parametrize(("factor_id", "field"), [
    ("quality.roic_persistence", "roic_history"), ("quality.gross_margin_stability", "gross_margin_history"),
    ("quality.free_cash_flow_conversion", "free_cash_flow_history"), ("growth.revenue_acceleration", "revenue_growth_history"),
    ("growth.earnings_acceleration", "operating_income_growth_history"), ("value.free_cash_flow_yield", "free_cash_flow"),
    ("value.earnings_yield", "operating_earnings"), ("capital_allocation.share_count_reduction", "diluted_share_count_history"),
    ("capital_allocation.reinvestment_efficiency", "operating_profit_history"), ("balance_sheet.net_debt_to_fcf", "net_debt"),
])
def test_each_factor_rejects_missing_and_malformed_inputs(factor_id: str, field: str) -> None:
    missing = _snapshot(); del missing["company_fundamentals"][field]
    with pytest.raises(ValueError): _factor(factor_id).evaluate(missing)
    malformed = _snapshot(); malformed["company_fundamentals"][field] = "invalid"
    with pytest.raises(ValueError): _factor(factor_id).evaluate(malformed)


@pytest.mark.parametrize("factor_id", ["value.free_cash_flow_yield", "value.earnings_yield", "quality.free_cash_flow_conversion", "capital_allocation.reinvestment_efficiency", "balance_sheet.net_debt_to_fcf"])
def test_zero_denominators_reject(factor_id: str) -> None:
    snapshot = _snapshot()
    if factor_id.startswith("value."): snapshot["company_fundamentals"]["enterprise_value"] = 0.0
    elif factor_id == "quality.free_cash_flow_conversion": snapshot["company_fundamentals"]["net_income_history"] = [0.0, 0.0, 0.0]
    elif factor_id == "capital_allocation.reinvestment_efficiency": snapshot["company_fundamentals"]["invested_capital_history"] = [100.0, 100.0]
    else: snapshot["company_fundamentals"]["free_cash_flow"] = 0.0
    with pytest.raises(ValueError, match="zero denominator"): _factor(factor_id).evaluate(snapshot)


def test_future_dated_observations_reject_and_directionality_is_economic() -> None:
    future = _snapshot(); future["company_fundamentals"]["roic_history"] = [{"value": 0.2, "filing_date": "2026-07-20"}]
    with pytest.raises(ValueError, match="future-dated observation rejected"): _factor("quality.roic_persistence").evaluate(future)
    low, high = _snapshot(), _snapshot(); low["company_fundamentals"]["free_cash_flow"] = 50.0; high["company_fundamentals"]["free_cash_flow"] = 150.0
    assert _factor("value.free_cash_flow_yield").evaluate(high) > _factor("value.free_cash_flow_yield").evaluate(low)
    low_debt, high_debt = _snapshot(), _snapshot(); high_debt["company_fundamentals"]["net_debt"] = 500.0
    assert _factor("balance_sheet.net_debt_to_fcf").evaluate(high_debt) < _factor("balance_sheet.net_debt_to_fcf").evaluate(low_debt)


@pytest.mark.parametrize(("factor_id", "field", "is_series"), [
    ("quality.roic_persistence", "roic_history", True), ("quality.gross_margin_stability", "gross_margin_history", True),
    ("quality.free_cash_flow_conversion", "free_cash_flow_history", True), ("growth.revenue_acceleration", "revenue_growth_history", True),
    ("growth.earnings_acceleration", "operating_income_growth_history", True), ("value.free_cash_flow_yield", "free_cash_flow", False),
    ("value.earnings_yield", "operating_earnings", False), ("capital_allocation.share_count_reduction", "diluted_share_count_history", True),
    ("capital_allocation.reinvestment_efficiency", "operating_profit_history", True), ("balance_sheet.net_debt_to_fcf", "net_debt", False),
])
def test_every_factor_rejects_future_dated_required_observation(factor_id: str, field: str, is_series: bool) -> None:
    snapshot = _snapshot()
    observation = {"value": 1.0, "publication_date": "2026-07-20"}
    snapshot["company_fundamentals"][field] = [observation] if is_series else observation
    with pytest.raises(ValueError, match="future-dated observation rejected"):
        _factor(factor_id).evaluate(snapshot)


def test_registry_artifacts_are_byte_identical(tmp_path: Path) -> None:
    registry = FactorRegistry()
    for item in core_factors(): registry.register(item)
    report = validate_registry(registry)
    registry.write_artifacts(tmp_path / "first", report); registry.write_artifacts(tmp_path / "second", report)
    assert {path.name: path.read_bytes() for path in (tmp_path / "first").iterdir()} == {path.name: path.read_bytes() for path in (tmp_path / "second").iterdir()}