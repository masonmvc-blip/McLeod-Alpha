from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.phase3 import ApprovalState, ExpectedReturnModel, Scenario, load_research_context
from engine.phase3.decision_engine import BlockingCode, DecisionModel
from engine.phase3.expected_return.model import ExpectedReturnResult
from engine.research_os_release import load_research_os_manifest, validate_research_os_release


REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_OS_MANIFEST_PATH = REPO_ROOT / "config" / "research_os_manifest.json"
EXPECTED_RETURN_MODEL_PATH = REPO_ROOT / "engine" / "phase3" / "expected_return" / "model.py"
EXPECTED_RETURN_MILESTONE_PATH = REPO_ROOT / "data" / "research" / "logs" / "ExpectedReturnEngine_Validated.json"


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


def _expected_return_result(ticker: str = "RKLB", approval: ApprovalState = ApprovalState.APPROVED_FOR_EIPV):
    context = load_research_context(ticker).with_approval_status(approval)
    model = ExpectedReturnModel()
    result = model.evaluate(
        context,
        market_price=100.0,
        bear_scenario=Scenario(intrinsic_value=80.0, probability=0.2, rationale="recession"),
        base_scenario=Scenario(intrinsic_value=110.0, probability=0.5, rationale="stable"),
        bull_scenario=Scenario(intrinsic_value=145.0, probability=0.3, rationale="upside"),
        investment_horizon_years=2.0,
        user_assumptions={"confidence_weight": 0.10, "uncertainty_penalty": 0.20},
    )
    return context, result


def test_decision_model_consumes_only_research_context_and_expected_return() -> None:
    context, expected_return = _expected_return_result()
    decision = DecisionModel().evaluate(context, expected_return)

    assert decision.ticker == context.ticker
    assert decision.expected_annual_return == expected_return.expected_annual_return
    assert decision.confidence_adjusted_expected_return == expected_return.confidence_adjusted_expected_return


def test_decision_model_never_reads_phase1_or_phase2_directly() -> None:
    source = (REPO_ROOT / "engine" / "phase3" / "decision_engine" / "model.py").read_text(encoding="utf-8")
    forbidden = [
        "engine.research_phase1",
        "phase1_facts",
        "phase1_review",
        "phase2_artifact.json",
        "phase2_review.md",
        "Path.read_text",
        "json.loads",
    ]
    for pattern in forbidden:
        assert pattern not in source


def test_unapproved_companies_are_never_eligible() -> None:
    context, expected_return = _expected_return_result(approval=ApprovalState.RESEARCH_ONLY)
    decision = DecisionModel().evaluate(context, expected_return)

    assert decision.decision_eligible is False
    assert BlockingCode.NOT_APPROVED in decision.blocking_reasons


def test_blocking_codes_are_deterministic() -> None:
    context, expected_return = _expected_return_result(approval=ApprovalState.RESEARCH_ONLY)
    model = DecisionModel()

    first = model.evaluate(context, expected_return)
    second = model.evaluate(context, expected_return)

    assert first.blocking_reasons == second.blocking_reasons
    assert first.decision_audit.deterministic_record == second.decision_audit.deterministic_record


def test_audit_is_immutable() -> None:
    context, expected_return = _expected_return_result()
    decision = DecisionModel().evaluate(context, expected_return)

    with pytest.raises(AttributeError):
        decision.decision_audit.steps.append(None)  # type: ignore[attr-defined]

    with pytest.raises(FrozenInstanceError):
        decision.decision_audit.steps[0].detail = "tamper"  # type: ignore[misc]


def test_identical_inputs_are_deterministic() -> None:
    context, expected_return = _expected_return_result()
    model = DecisionModel()

    first = model.evaluate(context, expected_return)
    second = model.evaluate(context, expected_return)

    assert first == second


def test_invalid_artifacts_rejected() -> None:
    context, expected_return = _expected_return_result()
    broken_context = replace(context, artifact_metadata={**context.artifact_metadata, "available": False, "status": "unavailable"})

    decision = DecisionModel().evaluate(broken_context, expected_return)

    assert decision.decision_eligible is False
    assert BlockingCode.INVALID_ARTIFACT in decision.blocking_reasons


def test_invalid_expected_return_rejected() -> None:
    context, expected_return = _expected_return_result()
    broken_expected = ExpectedReturnResult(
        ticker=expected_return.ticker,
        bear_annualized_return=expected_return.bear_annualized_return,
        base_annualized_return=expected_return.base_annualized_return,
        bull_annualized_return=expected_return.bull_annualized_return,
        expected_annual_return=float("nan"),
        expected_intrinsic_value=expected_return.expected_intrinsic_value,
        margin_of_safety=expected_return.margin_of_safety,
        expected_volatility_estimate=expected_return.expected_volatility_estimate,
        confidence_adjusted_expected_return=expected_return.confidence_adjusted_expected_return,
        calculation_audit=expected_return.calculation_audit,
    )

    decision = DecisionModel().evaluate(context, broken_expected)

    assert decision.decision_eligible is False
    assert BlockingCode.INVALID_EXPECTED_RETURN in decision.blocking_reasons


def test_invalid_artifact_states_include_stale_and_schema_mismatch() -> None:
    context, expected_return = _expected_return_result()
    stale = replace(
        context,
        artifact_metadata={
            **context.artifact_metadata,
            "generated_at": "2000-01-01T00:00:00+00:00",
            "schema_version": "broken",
        },
    )
    reference_time = datetime(2026, 7, 18, 18, 0, 0, tzinfo=timezone.utc)

    decision = DecisionModel().evaluate(stale, expected_return, reference_time=reference_time)

    assert BlockingCode.STALE_ARTIFACT in decision.blocking_reasons
    assert BlockingCode.SCHEMA_MISMATCH in decision.blocking_reasons


def test_expected_return_engine_and_research_os_remain_unchanged() -> None:
    before_manifest = RESEARCH_OS_MANIFEST_PATH.read_text(encoding="utf-8")
    before_expected_return_model = EXPECTED_RETURN_MODEL_PATH.read_text(encoding="utf-8")
    before_expected_return_milestone = EXPECTED_RETURN_MILESTONE_PATH.read_text(encoding="utf-8")

    context, expected_return = _expected_return_result()
    _ = DecisionModel().evaluate(context, expected_return)
    release = validate_research_os_release(load_research_os_manifest(), suite_results=_release_suite_map(), fail_closed=False)

    assert release.passed is True
    assert before_manifest == RESEARCH_OS_MANIFEST_PATH.read_text(encoding="utf-8")
    assert before_expected_return_model == EXPECTED_RETURN_MODEL_PATH.read_text(encoding="utf-8")
    assert before_expected_return_milestone == EXPECTED_RETURN_MILESTONE_PATH.read_text(encoding="utf-8")
