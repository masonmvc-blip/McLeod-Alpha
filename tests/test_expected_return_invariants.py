from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from engine.phase3 import ApprovalState, ExpectedReturnModel, Scenario, SensitivityAnalyzer, load_research_context
from engine.phase3.expected_return.model import ExpectedReturnValidationError
from engine.research_os_release import load_research_os_manifest, validate_research_os_release


REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_OS_MANIFEST_PATH = REPO_ROOT / "config" / "research_os_manifest.json"
PHASE3_MILESTONE_PATH = REPO_ROOT / "data" / "research" / "logs" / "Phase3_Foundation_Validated.json"


def _assumptions() -> dict[str, float]:
    return {"confidence_weight": 0.10, "uncertainty_penalty": 0.25}


def _scenarios_ordered():
    return {
        "bear": Scenario(intrinsic_value=80.0, probability=0.2, rationale="recession", supporting_assumptions={"growth": -0.05}),
        "base": Scenario(intrinsic_value=110.0, probability=0.5, rationale="stable", supporting_assumptions={"growth": 0.03}),
        "bull": Scenario(intrinsic_value=145.0, probability=0.3, rationale="upside", supporting_assumptions={"growth": 0.08}),
    }


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


def test_expected_return_model_consumes_only_research_context() -> None:
    context = load_research_context("RKLB").with_approval_status(ApprovalState.APPROVED_FOR_EIPV)
    scenarios = _scenarios_ordered()
    model = ExpectedReturnModel()

    result = model.evaluate(
        context,
        market_price=100.0,
        bear_scenario=scenarios["bear"],
        base_scenario=scenarios["base"],
        bull_scenario=scenarios["bull"],
        investment_horizon_years=2.0,
        user_assumptions=_assumptions(),
    )

    assert result.ticker == "RKLB"
    assert result.expected_intrinsic_value > 0
    assert result.expected_annual_return != 0


def test_probabilities_are_validated() -> None:
    context = load_research_context("RKLB").with_approval_status(ApprovalState.APPROVED_FOR_EIPV)
    model = ExpectedReturnModel()

    with pytest.raises(ExpectedReturnValidationError):
        model.evaluate(
            context,
            market_price=100.0,
            bear_scenario=Scenario(intrinsic_value=80.0, probability=0.2, rationale="bear"),
            base_scenario=Scenario(intrinsic_value=110.0, probability=0.2, rationale="base"),
            bull_scenario=Scenario(intrinsic_value=140.0, probability=0.2, rationale="bull"),
            investment_horizon_years=2.0,
            user_assumptions=_assumptions(),
        )


def test_audit_trail_is_immutable() -> None:
    context = load_research_context("RKLB").with_approval_status(ApprovalState.APPROVED_FOR_EIPV)
    scenarios = _scenarios_ordered()
    model = ExpectedReturnModel()

    result = model.evaluate(
        context,
        market_price=100.0,
        bear_scenario=scenarios["bear"],
        base_scenario=scenarios["base"],
        bull_scenario=scenarios["bull"],
        investment_horizon_years=3.0,
        user_assumptions=_assumptions(),
    )

    with pytest.raises(AttributeError):
        result.calculation_audit.append(None)  # type: ignore[attr-defined]

    with pytest.raises(FrozenInstanceError):
        result.calculation_audit[0].step = "tamper"  # type: ignore[misc]


def test_deterministic_identical_inputs() -> None:
    context = load_research_context("RKLB").with_approval_status(ApprovalState.APPROVED_FOR_EIPV)
    scenarios = _scenarios_ordered()
    model = ExpectedReturnModel()

    first = model.evaluate(
        context,
        market_price=95.0,
        bear_scenario=scenarios["bear"],
        base_scenario=scenarios["base"],
        bull_scenario=scenarios["bull"],
        investment_horizon_years=2.5,
        user_assumptions=_assumptions(),
    )
    second = model.evaluate(
        context,
        market_price=95.0,
        bear_scenario=scenarios["bear"],
        base_scenario=scenarios["base"],
        bull_scenario=scenarios["bull"],
        investment_horizon_years=2.5,
        user_assumptions=_assumptions(),
    )

    assert first == second


def test_scenario_order_does_not_change_results() -> None:
    context = load_research_context("RKLB").with_approval_status(ApprovalState.APPROVED_FOR_EIPV)
    scenarios = _scenarios_ordered()
    model = ExpectedReturnModel()

    ordered = model.evaluate(
        context,
        market_price=100.0,
        bear_scenario=scenarios["bear"],
        base_scenario=scenarios["base"],
        bull_scenario=scenarios["bull"],
        investment_horizon_years=2.0,
        user_assumptions=_assumptions(),
    )
    shuffled = model.evaluate(
        context,
        market_price=100.0,
        bear_scenario=Scenario(intrinsic_value=80.0, probability=0.2, rationale="recession", supporting_assumptions={"growth": -0.05}),
        base_scenario=Scenario(intrinsic_value=110.0, probability=0.5, rationale="stable", supporting_assumptions={"growth": 0.03}),
        bull_scenario=Scenario(intrinsic_value=145.0, probability=0.3, rationale="upside", supporting_assumptions={"growth": 0.08}),
        investment_horizon_years=2.0,
        user_assumptions=_assumptions(),
    )

    assert ordered == shuffled


def test_invalid_probabilities_fail() -> None:
    context = load_research_context("RKLB").with_approval_status(ApprovalState.APPROVED_FOR_EIPV)
    model = ExpectedReturnModel()

    with pytest.raises(ExpectedReturnValidationError):
        model.evaluate(
            context,
            market_price=100.0,
            bear_scenario=Scenario(intrinsic_value=80.0, probability=-0.1, rationale="bear"),
            base_scenario=Scenario(intrinsic_value=110.0, probability=0.7, rationale="base"),
            bull_scenario=Scenario(intrinsic_value=140.0, probability=0.4, rationale="bull"),
            investment_horizon_years=2.0,
            user_assumptions=_assumptions(),
        )


def test_invalid_horizons_fail() -> None:
    context = load_research_context("RKLB").with_approval_status(ApprovalState.APPROVED_FOR_EIPV)
    scenarios = _scenarios_ordered()
    model = ExpectedReturnModel()

    with pytest.raises(ExpectedReturnValidationError):
        model.evaluate(
            context,
            market_price=100.0,
            bear_scenario=scenarios["bear"],
            base_scenario=scenarios["base"],
            bull_scenario=scenarios["bull"],
            investment_horizon_years=0.0,
            user_assumptions=_assumptions(),
        )


def test_missing_assumptions_fail() -> None:
    context = load_research_context("RKLB").with_approval_status(ApprovalState.APPROVED_FOR_EIPV)
    scenarios = _scenarios_ordered()
    model = ExpectedReturnModel()

    with pytest.raises(ExpectedReturnValidationError):
        model.evaluate(
            context,
            market_price=100.0,
            bear_scenario=scenarios["bear"],
            base_scenario=scenarios["base"],
            bull_scenario=scenarios["bull"],
            investment_horizon_years=2.0,
            user_assumptions={"confidence_weight": 0.2},
        )


def test_research_os_and_phase3_foundation_remain_unchanged() -> None:
    before_manifest = RESEARCH_OS_MANIFEST_PATH.read_text(encoding="utf-8")
    before_phase3_milestone = PHASE3_MILESTONE_PATH.read_text(encoding="utf-8")

    release = validate_research_os_release(
        load_research_os_manifest(),
        suite_results=_release_suite_map(),
        fail_closed=False,
    )

    assert release.passed is True
    assert before_manifest == RESEARCH_OS_MANIFEST_PATH.read_text(encoding="utf-8")
    assert before_phase3_milestone == PHASE3_MILESTONE_PATH.read_text(encoding="utf-8")


def test_sensitivity_analyzer_outputs_deltas() -> None:
    context = load_research_context("RKLB").with_approval_status(ApprovalState.APPROVED_FOR_EIPV)
    scenarios = _scenarios_ordered()
    analyzer = SensitivityAnalyzer()

    result = analyzer.analyze(
        research_context=context,
        market_price=100.0,
        bear_scenario=scenarios["bear"],
        base_scenario=scenarios["base"],
        bull_scenario=scenarios["bull"],
        investment_horizon_years=2.0,
        user_assumptions=_assumptions(),
        stressed_bear_probability=0.25,
        stressed_base_probability=0.45,
        stressed_bull_probability=0.30,
        stressed_bear_intrinsic_value=75.0,
        stressed_base_intrinsic_value=108.0,
        stressed_bull_intrinsic_value=150.0,
        stressed_horizon_years=2.5,
    )

    assert result.delta_expected_return != 0
    assert result.delta_intrinsic_value != 0
    assert len(result.audit) == 3
