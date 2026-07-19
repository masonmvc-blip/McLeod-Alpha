from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from engine.phase3 import ApprovalState, ApprovalWorkflow, EIPVEngine, Phase3ApprovalError, ResearchContext, load_research_context
from engine.phase3.context import ResearchContextError
from engine.research_os_release import load_research_os_manifest, validate_research_os_release


REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_OS_MANIFEST_PATH = REPO_ROOT / "config" / "research_os_manifest.json"


def _phase3_sources() -> list[str]:
    return [
        (REPO_ROOT / "engine" / "phase3" / "__init__.py").read_text(encoding="utf-8"),
        (REPO_ROOT / "engine" / "phase3" / "approval.py").read_text(encoding="utf-8"),
        (REPO_ROOT / "engine" / "phase3" / "context.py").read_text(encoding="utf-8"),
        (REPO_ROOT / "engine" / "phase3" / "eipv.py").read_text(encoding="utf-8"),
    ]


def _approved_context(ticker: str = "RKLB") -> ResearchContext:
    context = load_research_context(ticker)
    return context.with_approval_status(ApprovalState.APPROVED_FOR_EIPV)


def test_research_context_is_the_only_research_interface() -> None:
    context = load_research_context("RKLB")

    assert isinstance(context, ResearchContext)
    assert set(context.__dataclass_fields__.keys()) == {
        "ticker",
        "overall_phase2_score",
        "component_scores",
        "confidence",
        "missing_inputs",
        "provenance",
        "approval_status",
        "artifact_metadata",
    }
    assert context.artifact_metadata["schema_version"]
    assert context.approval_status is ApprovalState.RESEARCH_ONLY


def test_phase3_never_reads_phase1_or_phase2_artifacts_directly() -> None:
    sources = _phase3_sources()
    forbidden = [
        "engine.research_phase1",
        "RKLB_phase1_facts.json",
        "NBIS_phase1_facts.json",
        "phase2_artifact.json",
        "phase2_review.md",
        "Path.read_text",
        "json.loads(path.read_text",
        "read_text(encoding=\"utf-8\")",
    ]

    for source in sources:
        for pattern in forbidden:
            assert pattern not in source


def test_unapproved_companies_cannot_produce_eipv() -> None:
    context = load_research_context("RKLB")
    engine = EIPVEngine()

    with pytest.raises(Phase3ApprovalError):
        engine.estimate(context, market_price=100.0, user_assumptions={}, scenario_assumptions={})


def test_approvals_require_explicit_transition() -> None:
    workflow = ApprovalWorkflow(ticker="RKLB")

    assert workflow.state is ApprovalState.RESEARCH_ONLY
    assert workflow.is_approved_for_eipv is False

    review_workflow = workflow.request_review(actor="analyst", reason="ready for review")
    approved_workflow = review_workflow.approve(actor="approver", reason="approved")

    assert review_workflow.state is ApprovalState.READY_FOR_REVIEW
    assert approved_workflow.state is ApprovalState.APPROVED_FOR_EIPV
    assert len(approved_workflow.audit_log) == 2
    assert approved_workflow.audit_log[0].from_state is ApprovalState.RESEARCH_ONLY
    assert approved_workflow.audit_log[1].to_state is ApprovalState.APPROVED_FOR_EIPV

    with pytest.raises(Phase3ApprovalError):
        workflow.approve(actor="approver", reason="skip review")


def test_audit_logs_are_immutable() -> None:
    workflow = ApprovalWorkflow(ticker="NBIS").request_review(actor="analyst", reason="queued")

    with pytest.raises(AttributeError):
        workflow.audit_log.append(None)  # type: ignore[attr-defined]

    with pytest.raises(FrozenInstanceError):
        workflow.audit_log[0].reason = "mutated"  # type: ignore[misc]


def test_deterministic_inputs_produce_deterministic_eipv() -> None:
    context = _approved_context("RKLB")
    engine = EIPVEngine()
    user_assumptions = {"horizon_years": 1.0, "expected_return_bias": 0.02, "signal_sensitivity": 0.25, "confidence_weight": 0.05}
    scenario_assumptions = {
        "bear": {"probability": 0.2, "return_delta": -0.10},
        "base": {"probability": 0.5, "return_delta": 0.0},
        "bull": {"probability": 0.3, "return_delta": 0.12},
    }

    first = engine.estimate(context, market_price=100.0, user_assumptions=user_assumptions, scenario_assumptions=scenario_assumptions)
    second = engine.estimate(context, market_price=100.0, user_assumptions=user_assumptions, scenario_assumptions=scenario_assumptions)

    assert first == second
    assert first.probability_weighted_intrinsic_value >= first.bear_intrinsic_value
    assert first.bull_intrinsic_value >= first.base_intrinsic_value
    assert first.audit_trail == second.audit_trail


def test_research_os_v1_remains_unchanged_before_and_after_phase3_usage() -> None:
    before = RESEARCH_OS_MANIFEST_PATH.read_text(encoding="utf-8")
    manifest = load_research_os_manifest()
    release_result = validate_research_os_release(manifest, suite_results={name: True for name in (
        "Phase 1 framework invariants",
        "Phase 1 regression suite",
        "Phase 2 framework invariants",
        "Phase 2 regression suite",
        "Phase 2 multi-company suite",
        "Phase 2 downstream integration suite",
        "Architecture invariant suite",
        "Release invariant suite",
        "Portfolio engine tests",
        "EIPV tests",
        "Morning CIO tests",
        "IBD integration tests",
    )}, fail_closed=False)

    assert release_result.passed is True
    assert before == RESEARCH_OS_MANIFEST_PATH.read_text(encoding="utf-8")


def test_phase3_context_loader_rejects_unavailable_context(monkeypatch) -> None:
    class _UnavailableAdapter:
        def load_ticker(self, ticker):
            raise ResearchContextError("unavailable")

    with pytest.raises(ResearchContextError):
        load_research_context("RKLB", adapter=_UnavailableAdapter())
