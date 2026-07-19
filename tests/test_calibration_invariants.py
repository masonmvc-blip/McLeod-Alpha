from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from engine.phase3 import ApprovalState, ExpectedReturnModel, Scenario, load_research_context
from engine.phase3.calibration import CalibrationModel, OutcomeRecord
from engine.phase3.calibration.model import CalibrationValidationError
from engine.phase3.decision_engine import DecisionModel
from engine.research_os_release import load_research_os_manifest, validate_research_os_release


REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_OS_MANIFEST_PATH = REPO_ROOT / "config" / "research_os_manifest.json"
EXPECTED_RETURN_MODEL_PATH = REPO_ROOT / "engine" / "phase3" / "expected_return" / "model.py"
DECISION_MODEL_PATH = REPO_ROOT / "engine" / "phase3" / "decision_engine" / "model.py"


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


def _inputs():
    context = load_research_context("RKLB").with_approval_status(ApprovalState.APPROVED_FOR_EIPV)
    expected = ExpectedReturnModel().evaluate(
        context,
        market_price=100.0,
        bear_scenario=Scenario(intrinsic_value=80.0, probability=0.2, rationale="recession"),
        base_scenario=Scenario(intrinsic_value=110.0, probability=0.5, rationale="stable"),
        bull_scenario=Scenario(intrinsic_value=140.0, probability=0.3, rationale="upside"),
        investment_horizon_years=2.0,
        user_assumptions={"confidence_weight": 0.10, "uncertainty_penalty": 0.20},
    )
    decision = DecisionModel().evaluate(context, expected)
    outcome = OutcomeRecord(
        ticker="RKLB",
        forecast_date="2026-07-01T00:00:00+00:00",
        evaluation_date="2026-07-18T00:00:00+00:00",
        expected_return=expected.expected_annual_return,
        realized_return=0.12,
        expected_intrinsic_value=expected.expected_intrinsic_value,
        realized_value=118.0,
        confidence=context.confidence,
        approval_state=context.approval_status,
        evaluation_horizon=2.0,
        provenance={"source": "paper_validation"},
    )
    return context, expected, decision, outcome


def test_calibration_model_consumes_only_expected_return_decision_outcome() -> None:
    _, expected, decision, outcome = _inputs()
    result = CalibrationModel().evaluate(expected, decision, outcome_record=outcome)

    assert result.ticker == "RKLB"
    assert result.measurement_state == "Measurable"


def test_no_direct_phase1_phase2_or_artifact_access() -> None:
    source = (REPO_ROOT / "engine" / "phase3" / "calibration" / "model.py").read_text(encoding="utf-8")
    forbidden = [
        "engine.research_phase1",
        "engine.phase2_research",
        "phase2_artifact.json",
        "phase2_review.md",
        "Path.read_text",
        "json.loads",
    ]

    for pattern in forbidden:
        assert pattern not in source


def test_deterministic_outputs() -> None:
    _, expected, decision, outcome = _inputs()
    model = CalibrationModel()

    first = model.evaluate(expected, decision, outcome_record=outcome)
    second = model.evaluate(expected, decision, outcome_record=outcome)

    assert first == second


def test_immutable_audit() -> None:
    _, expected, decision, outcome = _inputs()
    result = CalibrationModel().evaluate(expected, decision, outcome_record=outcome)

    with pytest.raises(AttributeError):
        result.calibration_audit.steps.append(None)  # type: ignore[attr-defined]

    with pytest.raises(FrozenInstanceError):
        result.calibration_audit.steps[0].detail = "mutate"  # type: ignore[misc]


def test_missing_outcomes_handled_explicitly() -> None:
    _, expected, decision, _ = _inputs()
    result = CalibrationModel().evaluate(expected, decision, outcome_record=None)

    assert result.measurable is False
    assert result.measurement_state == "Not Yet Measurable"
    assert result.forecast_error is None
    assert result.calibration_audit.missing_outcome_reasons


def test_invalid_input_types_fail() -> None:
    _, expected, decision, _ = _inputs()
    with pytest.raises(CalibrationValidationError):
        CalibrationModel().evaluate(expected, decision, outcome_record="bad")  # type: ignore[arg-type]


def test_research_os_expected_return_and_decision_engine_unchanged() -> None:
    before_manifest = RESEARCH_OS_MANIFEST_PATH.read_text(encoding="utf-8")
    before_expected = EXPECTED_RETURN_MODEL_PATH.read_text(encoding="utf-8")
    before_decision = DECISION_MODEL_PATH.read_text(encoding="utf-8")

    _, expected, decision, outcome = _inputs()
    _ = CalibrationModel().evaluate(expected, decision, outcome_record=outcome)
    release = validate_research_os_release(load_research_os_manifest(), suite_results=_release_suite_map(), fail_closed=False)

    assert release.passed is True
    assert before_manifest == RESEARCH_OS_MANIFEST_PATH.read_text(encoding="utf-8")
    assert before_expected == EXPECTED_RETURN_MODEL_PATH.read_text(encoding="utf-8")
    assert before_decision == DECISION_MODEL_PATH.read_text(encoding="utf-8")
