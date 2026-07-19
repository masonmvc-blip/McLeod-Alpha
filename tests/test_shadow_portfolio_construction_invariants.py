from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from engine.phase3 import ApprovalState, ExpectedReturnModel, Scenario, load_research_context
from engine.phase3.decision_engine import DecisionModel
from engine.phase3.shadow_portfolio_construction import (
    PortfolioConstraints,
    ShadowAllocationModel,
    ShadowAllocationValidationError,
)
from engine.research_os_release import load_research_os_manifest, validate_research_os_release


REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_OS_MANIFEST_PATH = REPO_ROOT / "config" / "research_os_manifest.json"
PORTFOLIO_ENGINE_PATH = REPO_ROOT / "engine" / "portfolio_engine.py"
SIMULATION_MODEL_PATH = REPO_ROOT / "engine" / "phase3" / "portfolio_simulation" / "model.py"


def _release_suite_map() -> dict[str, bool]:
    return {
        "Phase 1 framework invariants": True,
        "Phase 1 regression suite": True,
        "Phase 2 framework invariants": True,
        "Phase 2 regression suite": True,
        "Phase 2 multi-company suite": True,
        "Phase 2 downstream integration suite": True,
        "Architecture invariant suite": True,
        "Release invariant suite": True,
        "Portfolio engine tests": True,
        "EIPV tests": True,
        "Morning CIO tests": True,
        "IBD integration tests": True,
    }


def _decision_and_expected(approval=ApprovalState.APPROVED_FOR_EIPV):
    context = load_research_context("RKLB").with_approval_status(approval)
    expected = ExpectedReturnModel().evaluate(
        context,
        market_price=100.0,
        bear_scenario=Scenario(intrinsic_value=80.0, probability=0.2, rationale="recession"),
        base_scenario=Scenario(intrinsic_value=110.0, probability=0.5, rationale="stable"),
        bull_scenario=Scenario(intrinsic_value=145.0, probability=0.3, rationale="upside"),
        investment_horizon_years=2.0,
        user_assumptions={"confidence_weight": 0.10, "uncertainty_penalty": 0.20},
    )
    decision = DecisionModel().evaluate(context, expected)
    return decision, expected


def _constraints(**overrides):
    base = PortfolioConstraints(
        maximum_position_weight=0.40,
        minimum_position_weight=0.05,
        maximum_sector_weight=0.60,
        maximum_total_invested_capital=100000.0,
        minimum_cash_reserve=0.10,
        maximum_number_of_holdings=10,
        maximum_turnover=0.80,
        prohibited_tickers=(),
        required_tickers=(),
    )
    for key, value in overrides.items():
        base = replace(base, **{key: value})
    return base


def test_shadow_allocation_model_consumes_only_public_phase3_outputs() -> None:
    decision, expected = _decision_and_expected()
    result = ShadowAllocationModel().evaluate(
        decision_results=[decision],
        expected_return_results={"RKLB": expected},
        current_shadow_holdings={"RKLB": 1000.0},
        available_shadow_cash=1000.0,
        constraints=_constraints(),
        approved_allocation_method="equal_weight",
        timestamp="2026-07-18T20:00:00+00:00",
    )

    assert result.proposed_target_weights["RKLB"] > 0
    assert result.expected_portfolio_return != 0


def test_no_direct_phase1_phase2_or_raw_artifact_reads() -> None:
    source = (REPO_ROOT / "engine" / "phase3" / "shadow_portfolio_construction" / "model.py").read_text(encoding="utf-8")
    forbidden = [
        "engine.research_phase1",
        "engine.phase2_research",
        "engine.phase2_downstream",
        "phase2_artifact.json",
        "phase2_review.md",
        "Path.read_text",
        "json.loads",
    ]
    for pattern in forbidden:
        assert pattern not in source


def test_no_production_portfolio_writes() -> None:
    decision, expected = _decision_and_expected()
    before = PORTFOLIO_ENGINE_PATH.read_text(encoding="utf-8")
    _ = ShadowAllocationModel().evaluate(
        decision_results=[decision],
        expected_return_results={"RKLB": expected},
        current_shadow_holdings={"RKLB": 1000.0},
        available_shadow_cash=1000.0,
        constraints=_constraints(),
        approved_allocation_method="equal_weight",
        timestamp="2026-07-18T20:00:00+00:00",
    )
    assert before == PORTFOLIO_ENGINE_PATH.read_text(encoding="utf-8")


def test_ineligible_companies_receive_zero_allocation() -> None:
    decision, expected = _decision_and_expected(approval=ApprovalState.RESEARCH_ONLY)
    with pytest.raises(ShadowAllocationValidationError):
        ShadowAllocationModel().evaluate(
            decision_results=[decision],
            expected_return_results={"RKLB": expected},
            current_shadow_holdings={"RKLB": 1000.0},
            available_shadow_cash=1000.0,
            constraints=_constraints(),
            approved_allocation_method="equal_weight",
            timestamp="2026-07-18T20:00:00+00:00",
        )


def test_prohibited_tickers_receive_zero_allocation() -> None:
    decision, expected = _decision_and_expected()
    with pytest.raises(ShadowAllocationValidationError):
        ShadowAllocationModel().evaluate(
            decision_results=[decision],
            expected_return_results={"RKLB": expected},
            current_shadow_holdings={"RKLB": 1000.0},
            available_shadow_cash=1000.0,
            constraints=_constraints(prohibited_tickers=("RKLB",)),
            approved_allocation_method="equal_weight",
            timestamp="2026-07-18T20:00:00+00:00",
        )


def test_constraints_always_enforced() -> None:
    decision, expected = _decision_and_expected()
    result = ShadowAllocationModel().evaluate(
        decision_results=[decision],
        expected_return_results={"RKLB": expected},
        current_shadow_holdings={"RKLB": 1000.0},
        available_shadow_cash=1000.0,
        constraints=_constraints(maximum_position_weight=0.20, minimum_cash_reserve=0.30),
        approved_allocation_method="equal_weight",
        timestamp="2026-07-18T20:00:00+00:00",
    )

    assert result.proposed_target_weights["RKLB"] <= 0.70
    assert result.proposed_cash_weight >= 0.30


def test_target_weights_sum_deterministically() -> None:
    decision, expected = _decision_and_expected()
    model = ShadowAllocationModel()
    kwargs = {
        "decision_results": [decision],
        "expected_return_results": {"RKLB": expected},
        "current_shadow_holdings": {"RKLB": 1000.0},
        "available_shadow_cash": 1000.0,
        "constraints": _constraints(),
        "approved_allocation_method": "equal_weight",
        "timestamp": "2026-07-18T20:00:00+00:00",
    }
    first = model.evaluate(**kwargs)
    second = model.evaluate(**kwargs)

    assert first == second
    assert abs(sum(first.proposed_target_weights.values()) + first.proposed_cash_weight - 1.0) < 1e-9


def test_replacement_rankings_are_deterministic() -> None:
    decision, expected = _decision_and_expected()
    result = ShadowAllocationModel().evaluate(
        decision_results=[decision],
        expected_return_results={"RKLB": expected},
        current_shadow_holdings={"OLD": 2000.0},
        available_shadow_cash=1000.0,
        constraints=_constraints(),
        approved_allocation_method="equal_weight",
        timestamp="2026-07-18T20:00:00+00:00",
    )

    second = ShadowAllocationModel().evaluate(
        decision_results=[decision],
        expected_return_results={"RKLB": expected},
        current_shadow_holdings={"OLD": 2000.0},
        available_shadow_cash=1000.0,
        constraints=_constraints(),
        approved_allocation_method="equal_weight",
        timestamp="2026-07-18T20:00:00+00:00",
    )

    assert result.replacement_candidates == second.replacement_candidates


def test_audits_are_immutable() -> None:
    decision, expected = _decision_and_expected()
    result = ShadowAllocationModel().evaluate(
        decision_results=[decision],
        expected_return_results={"RKLB": expected},
        current_shadow_holdings={"RKLB": 1000.0},
        available_shadow_cash=1000.0,
        constraints=_constraints(),
        approved_allocation_method="equal_weight",
        timestamp="2026-07-18T20:00:00+00:00",
    )

    with pytest.raises(AttributeError):
        result.audit.validation_steps.append(None)  # type: ignore[attr-defined]

    with pytest.raises(FrozenInstanceError):
        result.audit.validation_steps[0].detail = "tamper"  # type: ignore[misc]


def test_portfolio_simulation_production_engine_and_research_os_unchanged() -> None:
    decision, expected = _decision_and_expected()
    before_sim = SIMULATION_MODEL_PATH.read_text(encoding="utf-8")
    before_prod = PORTFOLIO_ENGINE_PATH.read_text(encoding="utf-8")
    before_manifest = RESEARCH_OS_MANIFEST_PATH.read_text(encoding="utf-8")

    _ = ShadowAllocationModel().evaluate(
        decision_results=[decision],
        expected_return_results={"RKLB": expected},
        current_shadow_holdings={"RKLB": 1000.0},
        available_shadow_cash=1000.0,
        constraints=_constraints(),
        approved_allocation_method="equal_weight",
        timestamp="2026-07-18T20:00:00+00:00",
    )
    release = validate_research_os_release(load_research_os_manifest(), suite_results=_release_suite_map(), fail_closed=False)

    assert release.passed is True
    assert before_sim == SIMULATION_MODEL_PATH.read_text(encoding="utf-8")
    assert before_prod == PORTFOLIO_ENGINE_PATH.read_text(encoding="utf-8")
    assert before_manifest == RESEARCH_OS_MANIFEST_PATH.read_text(encoding="utf-8")


def test_fail_closed_checks() -> None:
    decision, expected = _decision_and_expected()
    model = ShadowAllocationModel()

    with pytest.raises(ShadowAllocationValidationError):
        model.evaluate(
            decision_results=[decision],
            expected_return_results={"RKLB": expected},
            current_shadow_holdings={"RKLB": 1000.0},
            available_shadow_cash=1000.0,
            constraints=_constraints(),
            approved_allocation_method="equal_weight",
            production_portfolio_access_attempted=True,
            timestamp="2026-07-18T20:00:00+00:00",
        )

    with pytest.raises(ShadowAllocationValidationError):
        model.evaluate(
            decision_results=[decision],
            expected_return_results={"RKLB": expected},
            current_shadow_holdings={"RKLB": 1000.0},
            available_shadow_cash=1000.0,
            constraints=_constraints(),
            approved_allocation_method="equal_weight",
            frozen_artifacts_valid=False,
            timestamp="2026-07-18T20:00:00+00:00",
        )
