from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from engine.phase3 import ApprovalState, ExpectedReturnModel, Scenario, load_research_context
from engine.phase3.calibration.model import CalibrationModel
from engine.phase3.calibration.types import OutcomeRecord
from engine.phase3.decision_engine import DecisionModel
from engine.phase3.portfolio_simulation import SimulationModel, SimulationScenario
from engine.research_os_release import load_research_os_manifest, validate_research_os_release


REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_OS_MANIFEST_PATH = REPO_ROOT / "config" / "research_os_manifest.json"
PORTFOLIO_ENGINE_PATH = REPO_ROOT / "engine" / "portfolio_engine.py"
CALIBRATION_MODEL_PATH = REPO_ROOT / "engine" / "phase3" / "calibration" / "model.py"
CALIBRATION_MILESTONE_PATH = REPO_ROOT / "data" / "research" / "logs" / "CalibrationEngine_Validated.json"


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


def _decision_and_expected():
    context = load_research_context("RKLB").with_approval_status(ApprovalState.APPROVED_FOR_EIPV)
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


def _historical_returns() -> dict[str, list[float]]:
    return {
        "RKLB": [0.01, -0.005, 0.012, 0.004, -0.002, 0.009, 0.003, -0.001],
    }


def test_simulation_model_consumes_only_public_phase3_outputs() -> None:
    decision, expected = _decision_and_expected()
    model = SimulationModel()

    result = model.evaluate(
        decision_outputs=[decision],
        expected_returns={"RKLB": expected},
        allocation_scenario=SimulationScenario(method="equal_weight", assumptions={"periods_per_year": 252}),
        historical_returns=_historical_returns(),
        start_date="2026-01-01",
        end_date="2026-07-18",
        benchmark="SPY",
        benchmark_returns=[0.004, 0.003, -0.002, 0.001, 0.002, 0.001, 0.0, 0.001],
    )

    assert result.backtest_result.benchmark == "SPY"
    assert result.simulation_audit.configuration_hash


def test_no_direct_phase1_phase2_or_raw_artifact_reads() -> None:
    source = (REPO_ROOT / "engine" / "phase3" / "portfolio_simulation" / "model.py").read_text(encoding="utf-8")
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


def test_deterministic_identical_simulations() -> None:
    decision, expected = _decision_and_expected()
    model = SimulationModel()
    kwargs = {
        "decision_outputs": [decision],
        "expected_returns": {"RKLB": expected},
        "allocation_scenario": SimulationScenario(method="confidence_weight", assumptions={"periods_per_year": 252}),
        "historical_returns": _historical_returns(),
        "start_date": "2026-01-01",
        "end_date": "2026-07-18",
        "benchmark": "SPY",
        "benchmark_returns": [0.004, 0.003, -0.002, 0.001, 0.002, 0.001, 0.0, 0.001],
    }
    first = model.evaluate(**kwargs)
    second = model.evaluate(**kwargs)

    assert first == second


def test_immutable_audit_and_backtest_result() -> None:
    decision, expected = _decision_and_expected()
    result = SimulationModel().evaluate(
        decision_outputs=[decision],
        expected_returns={"RKLB": expected},
        allocation_scenario=SimulationScenario(method="score_weight", assumptions={"periods_per_year": 252}),
        historical_returns=_historical_returns(),
        start_date="2026-01-01",
        end_date="2026-07-18",
        benchmark="SPY",
        benchmark_returns=[0.004, 0.003, -0.002, 0.001, 0.002, 0.001, 0.0, 0.001],
    )

    with pytest.raises(AttributeError):
        result.simulation_audit.validation_steps.append(None)  # type: ignore[attr-defined]

    with pytest.raises(FrozenInstanceError):
        result.backtest_result.cagr = 0.0  # type: ignore[misc]


def test_production_portfolio_engine_untouched() -> None:
    before = PORTFOLIO_ENGINE_PATH.read_text(encoding="utf-8")
    decision, expected = _decision_and_expected()
    _ = SimulationModel().evaluate(
        decision_outputs=[decision],
        expected_returns={"RKLB": expected},
        allocation_scenario=SimulationScenario(method="equal_weight", assumptions={"periods_per_year": 252}),
        historical_returns=_historical_returns(),
        start_date="2026-01-01",
        end_date="2026-07-18",
        benchmark="SPY",
        benchmark_returns=[0.004, 0.003, -0.002, 0.001, 0.002, 0.001, 0.0, 0.001],
    )
    assert before == PORTFOLIO_ENGINE_PATH.read_text(encoding="utf-8")


def test_research_os_and_calibration_engine_unchanged() -> None:
    before_manifest = RESEARCH_OS_MANIFEST_PATH.read_text(encoding="utf-8")
    before_calibration_model = CALIBRATION_MODEL_PATH.read_text(encoding="utf-8")
    before_calibration_milestone = CALIBRATION_MILESTONE_PATH.read_text(encoding="utf-8")

    decision, expected = _decision_and_expected()
    _ = SimulationModel().evaluate(
        decision_outputs=[decision],
        expected_returns={"RKLB": expected},
        allocation_scenario=SimulationScenario(method="equal_weight", assumptions={"periods_per_year": 252}),
        historical_returns=_historical_returns(),
        start_date="2026-01-01",
        end_date="2026-07-18",
        benchmark="SPY",
        benchmark_returns=[0.004, 0.003, -0.002, 0.001, 0.002, 0.001, 0.0, 0.001],
    )

    release = validate_research_os_release(load_research_os_manifest(), suite_results=_release_suite_map(), fail_closed=False)
    assert release.passed is True
    assert before_manifest == RESEARCH_OS_MANIFEST_PATH.read_text(encoding="utf-8")
    assert before_calibration_model == CALIBRATION_MODEL_PATH.read_text(encoding="utf-8")
    assert before_calibration_milestone == CALIBRATION_MILESTONE_PATH.read_text(encoding="utf-8")


def test_backtest_metrics_are_reported() -> None:
    decision, expected = _decision_and_expected()
    result = SimulationModel().evaluate(
        decision_outputs=[decision],
        expected_returns={"RKLB": expected},
        allocation_scenario=SimulationScenario(method="user_defined", user_weights={"RKLB": 1.0}, assumptions={"periods_per_year": 252, "risk_free_rate": 0.02}),
        historical_returns=_historical_returns(),
        start_date="2026-01-01",
        end_date="2026-07-18",
        benchmark="SPY",
        benchmark_returns=[0.004, 0.003, -0.002, 0.001, 0.002, 0.001, 0.0, 0.001],
    )

    assert isinstance(result.backtest_result.cagr, float)
    assert isinstance(result.backtest_result.max_drawdown, float)
    assert isinstance(result.concentration_metrics["hhi"], float)
    assert 0.0 <= result.cash_utilization <= 1.0


def test_calibration_consumes_simulation_outputs_indirectly_without_portfolio_actions() -> None:
    decision, expected = _decision_and_expected()
    _ = SimulationModel().evaluate(
        decision_outputs=[decision],
        expected_returns={"RKLB": expected},
        allocation_scenario=SimulationScenario(method="equal_weight", assumptions={"periods_per_year": 252}),
        historical_returns=_historical_returns(),
        start_date="2026-01-01",
        end_date="2026-07-18",
        benchmark="SPY",
        benchmark_returns=[0.004, 0.003, -0.002, 0.001, 0.002, 0.001, 0.0, 0.001],
    )

    outcome = OutcomeRecord(
        ticker="RKLB",
        forecast_date="2026-07-01T00:00:00+00:00",
        evaluation_date="2026-07-18T00:00:00+00:00",
        expected_return=expected.expected_annual_return,
        realized_return=0.05,
        expected_intrinsic_value=expected.expected_intrinsic_value,
        realized_value=106.0,
        confidence=decision.research_confidence,
        approval_state=decision.approval_status,
        evaluation_horizon=2.0,
        provenance={"source": "simulation_validation"},
    )
    calibration = CalibrationModel().evaluate(expected, decision, outcome_record=outcome)
    assert calibration.measurable is True
