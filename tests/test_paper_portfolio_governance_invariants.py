from __future__ import annotations

from dataclasses import FrozenInstanceError
from hashlib import sha256
import ast
import json
from pathlib import Path

import pytest

from engine.phase3.paper_portfolio_governance import (
    PaperGovernanceValidationError,
    PaperPortfolioState,
    PaperRecommendationModel,
    PaperRecommendationPolicy,
    PaperRecommendationStatus,
)
from engine.phase3.paper_portfolio_governance.policy import PaperPolicyValidationError
from engine.phase3.system_validation import SystemValidationModel


REPO_ROOT = Path(__file__).resolve().parent.parent

FROZEN_HASHES = {
    "config/research_os_manifest.json": "8133e50ecfad9dc31fc40d237c4409c4ca9573936603008b9f7ca30e3939a473",
    "engine/phase3/context.py": "2099134c8afee427adeb6b291b5f4e10c6b9f0fae9ca4313feb6018297e4c3f1",
    "engine/phase3/expected_return/model.py": "8e0d2b399872c6910bb242ccd204c3687cd7e817cc5138462d82981e1b73ceeb",
    "engine/phase3/decision_engine/model.py": "15f7a92d288314afbfcd1a2d19d1c1484bcd88beece2f8ce7aff4c3ead479beb",
    "engine/phase3/calibration/model.py": "e5977219a3abf15b34e69de0ceef05d6dfccae566934cafb77dd88156c1be367",
    "engine/phase3/portfolio_simulation/model.py": "a4565433daf6f3aa8a2673bd493f7265462109f93890b9f0c48b9965d213d385",
    "engine/phase3/shadow_portfolio_construction/model.py": "43d39d2fec949b6a6060741890e703f19341b2bce63ddce8bd6b481c37c9f53d",
    "engine/phase3/system_validation/model.py": "66b02a55a1cacf154035d9f9454eb4dc5a4c88836c525a49a68cd4de424da3ab",
    "engine/research_os_release.py": "bebb46337f73450af766b325eb6052a5a5db2276926e5166271b0be774f20a35",
    "engine/phase2_downstream.py": "7d25d7aa24be4177118ac41e209fc173e5e5c20607052a0ce4522352ad41804b",
    "engine/portfolio_engine.py": "4d39683c3a0fee762bf028f748216388aef5b68ed3b5ac149478f6e2f8afb63b",
}


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _governance_inputs() -> tuple:
    validation = SystemValidationModel(REPO_ROOT).evaluate()
    state = PaperPortfolioState(
        as_of_timestamp="2026-07-18T22:00:00+00:00",
        paper_cash=1000.0,
        paper_holdings={validation.decision.ticker: 1000.0},
        paper_weights={validation.decision.ticker: 0.50},
        total_paper_value=2000.0,
        provenance={"source": "governance_test"},
        version="1.0",
    )
    return (
        (validation.decision,),
        {validation.expected_return.ticker: validation.expected_return},
        {validation.calibration.ticker: validation.calibration},
        validation.simulation,
        validation.shadow_allocation,
        state,
    )


def test_governance_package_boundary_integrity() -> None:
    forbidden_import_prefixes = (
        "engine.research_phase1",
        "engine.phase2_research",
        "engine.phase2_downstream",
        "alpaca",
        "schwab",
        "ib_insync",
        "ccxt",
    )
    forbidden_raw_tokens = (
        "phase2_artifact.json",
        "phase2_review.md",
        "read_text(",
        "json.loads(path.read_text",
        "write_text(",
        "write_bytes(",
        "to_csv(",
        "to_json(",
    )

    for path in (REPO_ROOT / "engine" / "phase3" / "paper_portfolio_governance").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not any(alias.name.startswith(prefix) for prefix in forbidden_import_prefixes)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not any(node.module.startswith(prefix) for prefix in forbidden_import_prefixes)
        for token in forbidden_raw_tokens:
            assert token not in source


def test_no_autonomous_approval_and_required_approval_enforced() -> None:
    model = PaperRecommendationModel()
    decision_results, expected_map, calibration_map, simulation, shadow, state = _governance_inputs()
    base_policy = PaperRecommendationPolicy.default()
    policy = PaperRecommendationPolicy(
        **{
            **base_policy.__dict__,
            "maximum_position_weight": 1.0,
            "maximum_sector_weight": 1.0,
            "maximum_portfolio_turnover": 1.0,
            "minimum_cash_reserve": 0.0,
            "shadow_allocation_requirements": ("WEIGHTS_RECONCILE",),
        }
    )

    result = model.evaluate(
        decision_results=decision_results,
        expected_return_results=expected_map,
        calibration_results=calibration_map,
        simulation_result=simulation,
        shadow_allocation_result=shadow,
        policy=policy,
        paper_portfolio_state=state,
        human_approvals={},
        as_of_timestamp="2026-07-18T22:00:00+00:00",
    )

    assert all(status is PaperRecommendationStatus.PENDING_APPROVAL for status in result.recommendation_status.values())


def test_blocked_recommendations_receive_zero_allocation() -> None:
    model = PaperRecommendationModel()
    decision_results, expected_map, calibration_map, simulation, shadow, state = _governance_inputs()
    policy = PaperRecommendationPolicy.default()
    policy = PaperRecommendationPolicy(
        **{**policy.__dict__, "minimum_expected_return": 1.0}
    )

    result = model.evaluate(
        decision_results=decision_results,
        expected_return_results=expected_map,
        calibration_results=calibration_map,
        simulation_result=simulation,
        shadow_allocation_result=shadow,
        policy=policy,
        paper_portfolio_state=state,
        human_approvals={decision_results[0].ticker: policy.required_approvals},
        as_of_timestamp="2026-07-18T22:00:00+00:00",
    )

    assert all(record.status is PaperRecommendationStatus.BLOCKED for record in result.recommendation_records)
    assert all(record.proposed_paper_weight == 0.0 for record in result.recommendation_records)


def test_expired_recommendations_cannot_be_approved() -> None:
    model = PaperRecommendationModel()
    decision_results, expected_map, calibration_map, simulation, shadow, state = _governance_inputs()
    policy = PaperRecommendationPolicy.default()

    result = model.evaluate(
        decision_results=decision_results,
        expected_return_results=expected_map,
        calibration_results=calibration_map,
        simulation_result=simulation,
        shadow_allocation_result=shadow,
        policy=policy,
        paper_portfolio_state=state,
        human_approvals={decision_results[0].ticker: policy.required_approvals},
        as_of_timestamp="2099-01-01T00:00:00+00:00",
    )

    assert all(record.status is PaperRecommendationStatus.EXPIRED for record in result.recommendation_records)


def test_fail_closed_controls_trigger() -> None:
    model = PaperRecommendationModel()
    decision_results, expected_map, calibration_map, simulation, shadow, state = _governance_inputs()
    policy = PaperRecommendationPolicy.default()

    with pytest.raises(PaperGovernanceValidationError):
        model.evaluate(
            decision_results=decision_results,
            expected_return_results=expected_map,
            calibration_results=calibration_map,
            simulation_result=simulation,
            shadow_allocation_result=shadow,
            policy=policy,
            paper_portfolio_state=state,
            source_artifacts_valid=False,
        )

    with pytest.raises(PaperGovernanceValidationError):
        model.evaluate(
            decision_results=decision_results,
            expected_return_results=expected_map,
            calibration_results=calibration_map,
            simulation_result=simulation,
            shadow_allocation_result=shadow,
            policy=policy,
            paper_portfolio_state=state,
            broker_access_attempted=True,
        )


def test_policy_constraints_and_immutability_enforced() -> None:
    with pytest.raises(PaperPolicyValidationError):
        PaperRecommendationPolicy(
            version="x",
            allowed_recommendation_types=("HOLD",),
            minimum_decision_eligibility=True,
            minimum_expected_return=0.0,
            minimum_confidence=50.0,
            maximum_position_weight=0.4,
            maximum_sector_weight=0.6,
            maximum_portfolio_turnover=0.8,
            minimum_cash_reserve=1.0,
            maximum_number_of_holdings=10,
            prohibited_tickers=(),
            required_approvals=("risk",),
            maximum_recommendation_age_hours=72,
            calibration_requirements=("X",),
            simulation_requirements=("Y",),
            shadow_allocation_requirements=("Z",),
        ).validate()

    model = PaperRecommendationModel()
    decision_results, expected_map, calibration_map, simulation, shadow, state = _governance_inputs()
    result = model.evaluate(
        decision_results=decision_results,
        expected_return_results=expected_map,
        calibration_results=calibration_map,
        simulation_result=simulation,
        shadow_allocation_result=shadow,
        policy=PaperRecommendationPolicy.default(),
        paper_portfolio_state=state,
        human_approvals={},
        as_of_timestamp="2026-07-18T22:00:00+00:00",
    )

    with pytest.raises(FrozenInstanceError):
        result.governance_audit.policy_version = "mutated"  # type: ignore[misc]


def test_deterministic_outputs_and_recommendation_ids() -> None:
    model = PaperRecommendationModel()
    decision_results, expected_map, calibration_map, simulation, shadow, state = _governance_inputs()
    policy = PaperRecommendationPolicy.default()
    approvals = {decision_results[0].ticker: policy.required_approvals}

    first = model.evaluate(
        decision_results=decision_results,
        expected_return_results=expected_map,
        calibration_results=calibration_map,
        simulation_result=simulation,
        shadow_allocation_result=shadow,
        policy=policy,
        paper_portfolio_state=state,
        human_approvals=approvals,
        as_of_timestamp="2026-07-18T22:00:00+00:00",
    )
    second = model.evaluate(
        decision_results=decision_results,
        expected_return_results=expected_map,
        calibration_results=calibration_map,
        simulation_result=simulation,
        shadow_allocation_result=shadow,
        policy=policy,
        paper_portfolio_state=state,
        human_approvals=approvals,
        as_of_timestamp="2026-07-18T22:00:00+00:00",
    )

    assert first == second
    assert [row.recommendation_id for row in first.recommendation_records] == [row.recommendation_id for row in second.recommendation_records]


def test_paper_portfolio_state_isolation_from_production() -> None:
    before = _sha(REPO_ROOT / "engine" / "portfolio_engine.py")
    model = PaperRecommendationModel()
    decision_results, expected_map, calibration_map, simulation, shadow, state = _governance_inputs()
    _ = model.evaluate(
        decision_results=decision_results,
        expected_return_results=expected_map,
        calibration_results=calibration_map,
        simulation_result=simulation,
        shadow_allocation_result=shadow,
        policy=PaperRecommendationPolicy.default(),
        paper_portfolio_state=state,
        human_approvals={},
        as_of_timestamp="2026-07-18T22:00:00+00:00",
    )
    after = _sha(REPO_ROOT / "engine" / "portfolio_engine.py")
    assert before == after


def test_repository_hygiene_and_frozen_hashes_unchanged() -> None:
    classification = json.loads((REPO_ROOT / "reports" / "_hygiene_artifacts" / "conflicted_copy_classification.json").read_text(encoding="utf-8"))
    backup_moves = json.loads((REPO_ROOT / "reports" / "_hygiene_artifacts" / "noncanonical_backup_moves.json").read_text(encoding="utf-8"))

    assert classification["summary"]["total_inventory"] == 557
    assert classification["summary"]["deleted_count"] == 541
    assert len(backup_moves) == 22

    active_conflicted = [
        p
        for p in REPO_ROOT.rglob("*")
        if p.is_file()
        and "conflicted copy" in p.name.lower()
        and not str(p.relative_to(REPO_ROOT)).startswith("archive/")
        and not str(p.relative_to(REPO_ROOT)).startswith("backups/")
        and not str(p.relative_to(REPO_ROOT)).startswith(".venv/")
        and not str(p.relative_to(REPO_ROOT)).startswith("venv/")
    ]
    assert not active_conflicted

    actual = {path: _sha(REPO_ROOT / path) for path in FROZEN_HASHES}
    assert actual == FROZEN_HASHES
